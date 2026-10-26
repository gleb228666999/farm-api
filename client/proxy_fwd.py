#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy_fwd.py — 🌐 v0.27 ПРОЗРАЧНЫЙ ПРОКСИ-ФОРВАРДЕР клиента фермы.

Запускается задачей proxy.set (client main.py) на телефоне. Слушает локальный
порт (по умолчанию 127.0.0.1:8888). iptables (правила FARM_PROXY) заворачивает
в него ВЕСЬ исходящий TCP телефона. Для каждого соединения:

    приложение → [iptables REDIRECT] → proxy_fwd → SOCKS5 (логин/пароль) → интернет

Оригинальный адрес назначения берётся из сокет-опции SO_ORIGINAL_DST
(её выставляет ядро при REDIRECT) — приложение ничего не знает о прокси.

Поддержка: SOCKS5 upstream с авторизацией RFC 1929 (продавец «HTTPs / SOCKS5»).

Исключения (их фильтрует iptables, не форвардер): сам прокси-сервер, сервер
фермы, локальные/RFC1918 сети — иначе телефон потерял бы связь с сервером.

Тест-режим (песочница, без iptables): переменная окружения
FARM_PROXY_TEST_DST="host:port" — все соединения форвардятся на этот адрес
вместо SO_ORIGINAL_DST.

Запуск:
    python3 proxy_fwd.py --listen 127.0.0.1:8888 \
                         --upstream socks5://login:pass@ip:port \
                         --log  ../logs/proxy_fwd.log --pidfile ../info/proxy_fwd.pid
"""
import argparse
import asyncio
import os
import signal
import socket
import struct
import sys
import time
from urllib.parse import urlparse

SOL_IP = 0                      # IPPROTO_IP (на Android/Linux = 0)
SO_ORIGINAL_DST = 80            # классика netfilter (как в redsocks)

PROXY_NAME = "proxy_fwd v1.0"


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
        lf = getattr(log, "_file", None)
        if lf:
            lf.write(line + "\n")
            lf.flush()
    except Exception:
        pass


def original_dst(sock: socket.socket) -> tuple[str, int] | None:
    """Куда приложение КОГДА-ТО собиралось connectиться (до REDIRECT)."""
    try:
        data = sock.getsockopt(SOL_IP, SO_ORIGINAL_DST, 16)
        _family = struct.unpack("<H", data[0:2])[0]
        port = struct.unpack("!H", data[2:4])[0]
        ip = ".".join(str(b) for b in data[4:8])
        if port and ip != "0.0.0.0":
            return ip, port
    except Exception as e:
        log(f"⚠️ SO_ORIGINAL_DST не вышел: {e}")
    return None


async def socks5_connect(host: str, port: int,
                         login: str, password: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Поднять SOCKS5-соединение с upstream-прокси (RFC 1928 + авторизация)."""
    r, w = await asyncio.open_connection(host, port)
    # 1) приветствие: версия 5, методы: 0x02 (user/pass) и 0x00 (без авторизации)
    w.write(b"\x05\x02\x02\x00")
    await w.drain()
    log(f"… socks5 handshake {host}:{port}: приветствие отправлено")
    resp = await r.readexactly(2)
    if resp[0] != 5:
        raise RuntimeError(f"не SOCKS5: {resp!r}")
    log(f"… socks5 handshake: прокси выбрал метод {resp[1]}")
    if resp[1] == 2:
        # 2) subnegotiation логин/пароль (RFC 1929)
        lu = login.encode()[:255]
        pw = password.encode()[:255]
        w.write(b"\x01" + bytes([len(lu)]) + lu + bytes([len(pw)]) + pw)
        await w.drain()
        aresp = await r.readexactly(2)
        if aresp[1] != 0:
            raise RuntimeError("SOCKS5: неверный логин/пароль")
        log("… socks5 handshake: авторизация принята")
    elif resp[1] != 0:
        raise RuntimeError(f"SOCKS5: прокси отверг метод {resp[1]!r}")
    return r, w


async def socks5_request(r: asyncio.StreamReader, w: asyncio.StreamWriter,
                         dst_ip: str, dst_port: int):
    """CONNECT к конечной цели (ATYP=IPv4 — адрес у нас всегда числовой)."""
    ipb = bytes(int(p) for p in dst_ip.split("."))
    w.write(b"\x05\x01\x00\x01" + ipb + struct.pack("!H", dst_port))
    await w.drain()
    resp = await r.readexactly(10)   # VER REP RSV ATYP BND.ADDR(4) BND.PORT(2)
    if resp[1] != 0:
        raise RuntimeError(f"SOCKS5 CONNECT отвергнут (rep={resp[1]})")


async def pipe(rd: asyncio.StreamReader, wr: asyncio.StreamWriter, tag: str):
    try:
        while True:
            data = await rd.read(65536)
            if not data:
                break
            wr.write(data)
            await wr.drain()
    except Exception:
        pass
    finally:
        try:
            wr.close()
        except Exception:
            pass


async def handle(c_reader: asyncio.StreamReader, c_writer: asyncio.StreamWriter,
                 up_host: str, up_port: int, up_login: str, up_pass: str):
    peer = c_writer.get_extra_info("peername")
    dst = original_dst(c_writer.get_extra_info("socket"))
    if dst is None:
        test_dst = os.environ.get("FARM_PROXY_TEST_DST")
        if test_dst:
            th, _, tp = test_dst.rpartition(":")
            dst = (th, int(tp))
    if dst is None:
        log(f"⚠️ {peer}: не знаю исходный адрес (нет SO_ORIGINAL_DST и тест-dst) — закрываю")
        c_writer.close()
        return
    d_ip, d_port = dst
    t0 = time.time()
    try:
        s_reader, s_writer = await socks5_connect(up_host, up_port, up_login, up_pass)
        await socks5_request(s_reader, s_writer, d_ip, d_port)
    except Exception as e:
        log(f"❌ {peer} → {d_ip}:{d_port}: upstream отказал ({e})")
        c_writer.close()
        return
    log(f"➡️ {peer} → {d_ip}:{d_port} через {up_host}:{up_port} (за {(time.time()-t0)*1000:.0f}мс)")
    t1 = asyncio.create_task(pipe(c_reader, s_writer, "c→s"))
    t2 = asyncio.create_task(pipe(s_reader, c_writer, "s→c"))
    await asyncio.gather(t1, t2, return_exceptions=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:8888")
    ap.add_argument("--upstream", required=True)      # socks5://login:pass@ip:port
    ap.add_argument("--log", default="")
    ap.add_argument("--pidfile", default="")
    args = ap.parse_args()

    if args.log:
        try:
            os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
            log._file = open(args.log, "a", buffering=1)   # noqa
        except Exception:
            pass
    if args.pidfile:
        try:
            os.makedirs(os.path.dirname(args.pidfile) or ".", exist_ok=True)
            open(args.pidfile, "w").write(str(os.getpid()))
        except Exception:
            pass

    u = urlparse(args.upstream)
    scheme = (u.scheme or "socks5").lower()
    if scheme not in ("socks5", "socks5h"):
        log(f"❌ upstream {scheme}:// не поддерживается — нужен socks5 (у продавца «HTTPs / SOCKS5» выбирай SOCKS5)")
        sys.exit(2)
    up_host, up_port = u.hostname, u.port or 1080
    up_login, up_pass = u.username or "", u.password or ""

    lh, _, lp = args.listen.rpartition(":")
    lport = int(lp or 8888)

    def _sigterm(_sig, _frm):
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    log(f"🚀 {PROXY_NAME}: слушаю {lh or '127.0.0.1'}:{lport} → socks5://"
        f"{up_login}:{'*' * max(len(up_pass), 1)}@{up_host}:{up_port}"
        f"{' (ТЕСТ-dst=' + os.environ.get('FARM_PROXY_TEST_DST', '') + ')' if os.environ.get('FARM_PROXY_TEST_DST') else ''}")

    async def _handler(r, w):
        await handle(r, w, up_host, up_port, up_login, up_pass)

    server = await asyncio.start_server(_handler, lh or "127.0.0.1", lport)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
