#!/usr/bin/env python3
"""
🚜 Farm Bootstrap — установка клиента на телефон (Termux).

    python bootstrap.py                # установить + настроить + запустить
    python bootstrap.py --no-run       # только установить/обновить файлы

Без вопросов. При первом запуске (или миграции) сам ставит неубиваемость v2,
убивает старый клиент и запускает supervisor с НОВЫМ кодом.
"""
import sys
import os
import json
import glob
import time
import signal
import hashlib
import secrets
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

DEFAULT_SERVER = "http://gleb2009kiler-55019.portmap.host:55019"
BASE = Path.home() / "farm"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FarmBootstrap/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def kill_running_client() -> int:
    """Убить работающий клиент, чтобы supervisor поднял СВЕЖИЙ код.
    (иначе старый продолжит крутиться в памяти до первой смерти)"""
    killed = 0
    for cmdf in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdf, "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace")
            if "farm/main.py" in cmd:
                os.kill(int(cmdf.split("/")[2]), signal.SIGTERM)
                killed += 1
        except Exception:
            continue
    if killed:
        time.sleep(2)
    return killed


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_run = "--no-run" in sys.argv
    server = (args[0] if args else DEFAULT_SERVER).rstrip("/")

    print("🚜 Farm Bootstrap")
    print(f"   Папка:  {BASE}")
    print(f"   Сервер: {server}")

    # --- 1. манифест ---
    try:
        manifest = json.loads(http_get(f"{server}/client/manifest"))
    except Exception as e:
        print(f"❌ Сервер недоступен: {e}")
        sys.exit(1)

    files = manifest.get("files", [])
    if not files:
        print("❌ На сервере нет файлов клиента (~/farm-server/client/ пуста?)")
        sys.exit(1)
    print(f"📦 Файлов на сервере: {len(files)}")

    # --- 2. скачивание ---
    updated, skipped = 0, 0
    for f in files:
        dest = BASE / f["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and sha256(dest.read_bytes()) == f["sha256"]:
            skipped += 1
            continue
        q = urllib.parse.quote(f["path"], safe="/")
        content = http_get(f"{server}/client/file?path={q}")
        if sha256(content) != f["sha256"]:
            print(f"❌ sha256 не совпал: {f['path']}")
            sys.exit(1)
        dest.write_bytes(content)
        print(f"   ✅ {f['path']} ({f['size']} б)")
        updated += 1
    print(f"   = актуальных: {skipped}")

    # --- 3. служебные папки ---
    for d in ("info", "logs"):
        (BASE / d).mkdir(parents=True, exist_ok=True)

    # --- 4. config.json ---
    cfg_path = BASE / "config.json"
    if cfg_path.exists():
        try:
            device_id = json.loads(cfg_path.read_text()).get("device_id", "?")
            print(f"   ⚙️ config.json есть, device_id = {device_id}")
        except Exception:
            pass
    else:
        device_id = f"phone_{secrets.token_hex(3)}"
        cfg = {
            "device_id": device_id,
            "server_url": server,
            "ws_url": server.replace("http://", "ws://").replace("https://", "wss://") + "/ws",
            "heartbeat_interval": 30,
        }
        cfg_path.write_text(json.dumps(cfg, indent=2))
        print(f"   ⚙️ Создан config.json, device_id = {device_id}")

    # --- 5. зависимости ---
    try:
       import websockets  # noqa: F401
    except ImportError:
        print("   📚 Устанавливаю websockets...")
        os.system(f"{sys.executable} -m pip install -q websockets")

    print(f"✅ Файлы готовы! Обновлено: {updated}")

    # --- 6. запуск ---
    if no_run:
        print("Запуск: sh ~/farm/farm_start.sh")
        return

    setup_marker = BASE / "info" / "setup_done.json"
    need_setup = True
    if setup_marker.exists():
        try:
            need_setup = json.loads(setup_marker.read_text()).get("v") != 5
        except Exception:
            pass
    if need_setup:
        print("\n🔧 Устанавливаю неубиваемость v2 (авто)...")
        r = subprocess.run([sys.executable, str(BASE / "setup.py"), "--no-start"])
        if r.returncode != 0:
            print("⚠️ позже: python ~/farm/setup.py")
    else:
        print("✅ Неубиваемость v2 уже настроена")

    # старый клиент может крутиться со старым кодом — приберём,
    # supervisor поднимет уже с новыми файлами
    killed = kill_running_client()
    if killed:
        print(f"♻️ Остановлен старый клиент ({killed} шт.) — supervisor поднимет новый")

    print("🚀 Запускаю supervisor...\n")
    os.execv("/data/data/com.termux/files/usr/bin/sh",
             ["sh", str(BASE / "supervisor.sh")])


if __name__ == "__main__":
    main()
