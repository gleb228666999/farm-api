#!/usr/bin/env python3
"""
🚜 Farm Server v0.6
- /ws                      телефоны (hello, heartbeat, events, task, result)
- /client/manifest|file    раздача клиента (sha256)
- /bootstrap.py            установщик для телефонов
- /api/devices|send|broadcast|results|update
- /api/events              события фарма из SQLite (этап 2)
- /api/groups              группы устройств (этап 4) + send в группу
- /api/pool                🍪 пул кук на сервере (добавить/удалить/бронь/архив)
- /api/schedule            ⏰ расписание: рега ежедневно + сбор по времени МСК (2 пачки)
-                          v0.6: фармеры = все онлайн-устройства кроме сборщиков (не только
-                          цифровые id); день помечается только при реальном старте;
-                          spawn_bg (GC не убивает задачи); валидация ЧЧ:ММ; честные ответы кнопок
- /                        дашборд (dashboard.html)
- v0.15: /api/devices/{id}/send, /api/broadcast, /api/groups/{name}/send —
          type:"task" ставится АВТОМАТИЧЕСКИ (клиент отвечает только на type=task)
- v0.7: 🛡 БЕЗОПАСНЫЙ РЕЖИМ — kill-switch регы акков:
    • rega_enabled=false в расписании (по умолчанию ВЫКЛЮЧЕНА — чтобы случайно
      не удалились/не перезаписались акки с лутом); кнопки «Рега сейчас» и
      расписание отказывают с объяснением;
    • POST /api/rega/switch — тумблер: сохраняет флаг + шлёт rega.switch всем
      онлайн-телефонам (клиент пишет info/rega_switch.json — фарм-гейт тоже
      перестаёт регистрировать);
    • при hello сервер сам отправляет rega.switch — офлайн-телефоны догоняют
      состояние при каждом коннекте;
    • сбор v2: сборщикам (collector-*) даётся 90с head-start (байпас+выход в
      приватки) до пачки 1; предупреждение, если сборщиков нет (лут НЕ теряется —
      treid.lua на фармерах сам ждёт цели);
    • cookie.check НЕ шлётся во время активного сбора (не мешать трейду).
"""
import json
import time
import hashlib
import re
import secrets
import asyncio
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

app = FastAPI(title="Farm Server")

BASE_DIR = Path(__file__).parent
CLIENT_DIR = BASE_DIR / "client"
BOOTSTRAP = BASE_DIR / "bootstrap.py"
DASHBOARD_FILE = BASE_DIR / "dashboard.html"
RESULTS_TTL = 3600

devices: dict = {}   # device_id -> {"ws","queue","info","client_version","last_seen","connected_at"}
results: dict = {}   # task_id   -> {"status","data","device_id","ts"}

# фоновые задачи (рега/сбор/планировщик): ДЕРЖИМ ССЫЛКУ — create_task без ссылки
# собирается GC-ом и задача молча умирает посреди работы (документированная ловушка)
_BG_TASKS: set = set()


def spawn_bg(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return t

# фоновые задачи (рега/сбор/планировщик): ДЕРЖИМ ССЫЛКУ — create_task без ссылки
# собирается GC-ом и задача молча умирает посреди работы (документированная ловушка)
_BG_TASKS: set = set()


def spawn_bg(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return t


# ---------- SQLite (этапы 2+4) ----------

DB_PATH = BASE_DIR / "farm.db"
DB_LOCK = threading.Lock()


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS events(
        id        TEXT PRIMARY KEY,   -- id события от телефона (защита от дублей)
        device_id TEXT,
        ts        REAL,               -- когда случилось (часы телефона)
        type      TEXT,               -- farm.start/bypass.ok/farm.restart/...
        info      TEXT,               -- JSON-детали
        recv      REAL)               -- когда сервер получил""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
    conn.execute("""CREATE TABLE IF NOT EXISTS groups(
        name    TEXT PRIMARY KEY,
        devices TEXT,                 -- JSON-список device_id
        created REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pool(
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        cookie     TEXT UNIQUE NOT NULL,
        nick       TEXT DEFAULT '',
        pass       TEXT DEFAULT '',
        status     TEXT DEFAULT 'pool',  -- pool | archive
        claimed_by TEXT,                  -- кто забронировал (device_id)
        claimed_ts REAL,                  -- время брони (TTL ниже)
        added_ts   REAL,
        source     TEXT DEFAULT '')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pool_status ON pool(status)")
    conn.commit()
    return conn


DB = init_db()


def db_events_insert(device_id: str, events: list) -> int:
    """INSERT OR IGNORE — дубликаты (повторная отправка батча) отсекаются по id."""
    inserted = 0
    with DB_LOCK:
        for ev in events:
            try:
                cur = DB.execute(
                    "INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                    (str(ev.get("id")), device_id,
                     float(ev.get("ts") or now()), str(ev.get("type") or "?"),
                     json.dumps(ev.get("info") or {}, ensure_ascii=False), now()))
                inserted += cur.rowcount
            except Exception:
                pass
        DB.commit()
    return inserted


def db_group_map() -> dict:
    """device_id -> [группы]"""
    with DB_LOCK:
        rows = DB.execute("SELECT name, devices FROM groups").fetchall()
    gmap = {}
    for name, devs in rows:
        try:
            for did in json.loads(devs or "[]"):
                gmap.setdefault(did, []).append(name)
        except Exception:
            pass
    return gmap


def now(): return time.time()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def remember_result(task_id, status, device_id, data=None):
    for tid in [t for t, r in results.items() if now() - r["ts"] > RESULTS_TTL]:
        results.pop(tid)
    results[task_id] = {"status": status, "data": data, "device_id": device_id, "ts": now()}


# ---------- раздача клиента ----------

def scan_client_dir() -> list:
    files = []
    if not CLIENT_DIR.exists():
        return files
    for p in sorted(CLIENT_DIR.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(CLIENT_DIR).as_posix()
            files.append({"path": rel,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                          "size": p.stat().st_size})
    return files


def safe_client_path(rel: str) -> Path | None:
    if not rel or ".." in Path(rel).parts:
        return None
    p = (CLIENT_DIR / rel).resolve()
    if not str(p).startswith(str(CLIENT_DIR.resolve())):
        return None
    return p


@app.get("/client/manifest")
async def client_manifest():
    return {"files": scan_client_dir(), "server_time": now()}


@app.get("/client/file")
async def client_file(path: str = Query(...)):
    p = safe_client_path(path)
    if p is None or not p.is_file():
        raise HTTPException(404, "not found")
    return Response(content=p.read_bytes(), media_type="application/octet-stream")


@app.get("/bootstrap.py")
async def get_bootstrap():
    if not BOOTSTRAP.is_file():
        raise HTTPException(404, "bootstrap.py not found on server")
    return Response(content=BOOTSTRAP.read_bytes(), media_type="application/octet-stream")


# ---------- WebSocket ----------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    device_id = None
    queue: asyncio.Queue = asyncio.Queue()
    sender_task = None

    async def sender():
        while True:
            msg = await queue.get()
            await ws.send_text(json.dumps(msg))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get("type")

            if t == "hello":
                device_id = msg.get("device_id") or f"anon_{secrets.token_hex(3)}"
                devices[device_id] = {
                    "ws": ws, "queue": queue,
                    "info": msg.get("info", {}),
                    "client_version": msg.get("client_version"),
                    "last_seen": now(), "connected_at": now(),
                }
                if sender_task is None:
                    sender_task = asyncio.create_task(sender())
                log(f"[+] {device_id} connected ({len(devices)} online)")
                await queue.put({"type": "welcome", "server_time": now(), "online": len(devices)})
                # 🛡 v0.7: синхронизация kill-switch регы при каждом коннекте —
                # телефон, который был офлайн во время переключения тумблера,
                # догоняет состояние сам (пишет info/rega_switch.json)
                try:
                    cfg_now = load_schedule()
                    await queue.put({
                        "type": "task", "task": "rega.switch",
                        "payload": {"enabled": bool(cfg_now.get("rega_enabled", False)),
                                    "source": "server-hello-sync"},
                        "task_id": f"regasw_{secrets.token_hex(3)}"})
                except Exception as e:
                    log(f"[!] rega.switch sync {device_id}: {e}")

            elif t == "heartbeat":
                d = devices.get(device_id)
                if d:
                    d["last_seen"] = now()
                    if "battery" in msg:
                        d["info"]["battery"] = msg["battery"]
                    if "farm" in msg:
                        d["info"]["farm"] = msg["farm"]   # last_key_time → 🔑 дашборд
                await queue.put({"type": "heartbeat_ack", "server_time": now()})

            elif t == "events":
                # ЭТАП 2: события фарма → SQLite. ack с числом обработанных —
                # клиент после него двигает offset (outbox)
                evs = [e for e in (msg.get("events") or [])[:200] if isinstance(e, dict)]
                try:
                    n_ins = db_events_insert(device_id, evs)
                    if n_ins:
                        log(f"[📅] {device_id}: +{n_ins} событий (из {len(evs)})")
                except Exception as e:
                    log(f"[!] events db {device_id}: {e}")
                # рега закончилась на этом телефоне → убираем из pending
                if any(e.get("type") in ("rega.done", "rega.fail", "rega.stop")
                       for e in evs):
                    try:
                        st = load_sched_state()
                        if device_id in st.get("rega_pending", []):
                            st["rega_pending"].remove(device_id)
                            save_sched_state(st)
                            log(f"[🆕] {device_id}: рега закончилась (pending={st['rega_pending']})")
                    except Exception:
                        pass
                await queue.put({"type": "events_ack", "accepted": len(evs)})

            elif t == "result":
                remember_result(msg.get("task_id", "?"), "done", device_id, msg.get("data"))
                log(f"[✓] result from {device_id}: {msg.get('task_id')}")

            elif t == "ping":
                await queue.put({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log(f"[!] ws error {device_id}: {type(e).__name__}: {e}")
    finally:
        if sender_task:
            sender_task.cancel()
        if device_id and devices.get(device_id, {}).get("ws") is ws:
            devices.pop(device_id, None)
        log(f"[-] {device_id} disconnected ({len(devices)} online)")


# ---------- API ----------

@app.get("/api/devices")
async def api_devices():
    gmap = db_group_map()
    out = []
    for did, d in devices.items():
        out.append({
            "device_id": did,
            "online": now() - d["last_seen"] < 90,
            "last_seen_sec": int(now() - d["last_seen"]),
            "client_version": d.get("client_version"),
            "info": d.get("info", {}),
            "uptime_sec": int(now() - d["connected_at"]),
            "groups": gmap.get(did, []),
        })
    return {"count": len(out), "devices": out}


@app.post("/api/devices/{device_id}/send")
async def api_send(device_id: str, body: dict):
    d = devices.get(device_id)
    if not d:
        raise HTTPException(404, "device not connected")
    task_id = body.pop("task_id", None) or f"t_{secrets.token_hex(4)}"
    body["task_id"] = task_id
    body.setdefault("type", "task")   # v0.15: клиент отвечает только на type=="task"
    await d["queue"].put(body)
    remember_result(task_id, "sent", device_id)
    return {"task_id": task_id, "status": "sent"}


@app.post("/api/broadcast")
async def api_broadcast(body: dict):
    sent = []
    for did, d in list(devices.items()):
        task_id = f"t_{secrets.token_hex(4)}"
        msg = dict(body)
        msg["task_id"] = task_id
        msg.setdefault("type", "task")   # v0.15
        await d["queue"].put(msg)
        remember_result(task_id, "sent", did)
        sent.append(task_id)
    return {"sent": len(sent), "task_ids": sent}


@app.get("/api/results/{task_id}")
async def api_result(task_id: str):
    if task_id not in results:
        raise HTTPException(404, "no such task")
    return results[task_id]


@app.post("/api/update")
async def api_update(body: dict):
    """{"all": true} — всем, или {"device_id": "phone_01"} — одному"""
    if body.get("all"):
        targets = list(devices.keys())
    else:
        did = body.get("device_id")
        targets = [did] if did in devices else []
    if not targets:
        raise HTTPException(404, "нет подключённых устройств")
    sent = []
    for did in targets:
        task_id = f"t_{secrets.token_hex(4)}"
        await devices[did]["queue"].put(
            {"type": "task", "task": "update", "task_id": task_id})
        remember_result(task_id, "sent", did)
        sent.append({"device_id": did, "task_id": task_id})
    return {"sent": sent}


@app.get("/health")
async def health():
    return {"ok": True, "host": "debian", "devices": len(devices), "time": now()}


# ---------- События фарма (этап 2) ----------

@app.get("/api/events")
async def api_events(device_id: str = None, type: str = None, limit: int = 100):
    q = "SELECT id, device_id, ts, type, info, recv FROM events"
    conds, args = [], []
    if device_id:
        conds.append("device_id=?"); args.append(device_id)
    if type:
        conds.append("type=?"); args.append(type)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(min(max(limit, 1), 500))
    with DB_LOCK:
        rows = DB.execute(q, args).fetchall()
    return {"count": len(rows), "events": [
        {"id": r[0], "device_id": r[1], "ts": r[2], "type": r[3],
         "info": json.loads(r[4] or "{}"), "recv": r[5]} for r in rows]}


@app.delete("/api/events")
async def api_events_clear():
    with DB_LOCK:
        DB.execute("DELETE FROM events")
        DB.commit()
    return {"ok": True, "note": "история событий очищена"}


# ---------- Группы устройств (этап 4) ----------

@app.get("/api/groups")
async def api_groups():
    with DB_LOCK:
        rows = DB.execute("SELECT name, devices, created FROM groups ORDER BY name").fetchall()
    return {"groups": [
        {"name": r[0], "devices": json.loads(r[1] or "[]"), "created": r[2]}
        for r in rows]}


@app.post("/api/groups")
async def api_groups_save(body: dict):
    """{"name": "bazа", "devices": ["phone_01", "phone_02"]} — создать/заменить"""
    name = str(body.get("name") or "").strip()
    members = body.get("devices") or []
    if not name:
        raise HTTPException(400, "no name")
    if not isinstance(members, list):
        raise HTTPException(400, "devices must be a list")
    with DB_LOCK:
        DB.execute("INSERT OR REPLACE INTO groups VALUES(?,?,?)",
                   (name, json.dumps(members), now()))
        DB.commit()
    return {"ok": True, "name": name, "count": len(members)}


@app.delete("/api/groups/{name}")
async def api_groups_delete(name: str):
    with DB_LOCK:
        DB.execute("DELETE FROM groups WHERE name=?", (name,))
        DB.commit()
    return {"ok": True}


@app.post("/api/groups/{name}/send")
async def api_groups_send(name: str, body: dict):
    """Задача всем ОНЛАЙН-устройствам группы (офлайн просто вернутся списком)"""
    with DB_LOCK:
        row = DB.execute("SELECT devices FROM groups WHERE name=?", (name,)).fetchone()
    if not row:
        raise HTTPException(404, "no such group")
    members = json.loads(row[0] or "[]")
    sent, offline = [], []
    task_id = None
    for did in members:
        d = devices.get(did)
        if not d:
            offline.append(did)
            continue
        task_id = f"t_{secrets.token_hex(4)}"
        msg = dict(body)
        msg["task_id"] = task_id
        msg.setdefault("type", "task")   # v0.15
        await d["queue"].put(msg)
        remember_result(task_id, "sent", did)
        sent.append({"device_id": did, "task_id": task_id})
    return {"group": name, "members": len(members),
            "sent": sent, "offline": offline}


# ============================================================
# 🍪 ПУЛ КУК НА СЕРВЕРЕ (v0.5)
# ============================================================
# Статусы: pool (свободные куки) → телефон берёт при недоборе;
#          archive (отработанные) → крайний резерв, если пул пуст.
# Бронь (claimed_by/claimed_ts) с TTL — одну куку два телефона не получат.

CLAIM_TTL = 2700          # сек (45 мин)
RE_COOKIE = re.compile(r'(_\|WARNING:\S+)')
RE_RS = re.compile(r'^\.?roblosecurity\s*=\s*(\S+)\s*$', re.I)


def parse_pool_text(text: str) -> list:
    """Парсер из v18.8: nick:/pass:/.ROBLOSECURITY=..., куки построчно, голый токен."""
    entries, nick, pwd = [], "", ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or set(line) <= set("-—=·_. "):
            continue
        if line.startswith("/"):
            continue
        low = line.lower()
        if low.startswith(("nick:", "ник:", "username:", "login:", "логин:")):
            nick = line.split(":", 1)[1].strip()
            continue
        if low.startswith(("pass:", "пароль:", "password:")):
            pwd = line.split(":", 1)[1].strip()
            continue
        if low.startswith(("телефон:", "phone:", "from:")):
            continue
        m = RE_COOKIE.search(line)
        if m:
            entries.append({"nick": nick, "pass": pwd, "cookie": m.group(1)})
            continue
        m2 = RE_RS.match(line)
        if m2:
            entries.append({"nick": nick, "pass": pwd, "cookie": m2.group(1)})
            continue
        if len(line) > 60 and "_" in line:      # голый токен
            entries.append({"nick": nick, "pass": pwd, "cookie": line})
    return entries


def db_pool_add(entries: list, status: str = "pool", source: str = "dashboard") -> int:
    added = 0
    with DB_LOCK:
        for e in entries:
            c = (e.get("cookie") or "").strip()
            if len(c) < 40:
                continue
            try:
                DB.execute(
                    "INSERT OR IGNORE INTO pool(cookie,nick,pass,status,added_ts,source) VALUES(?,?,?,?,?,?)",
                    (c, e.get("nick", ""), e.get("pass", ""), status, now(), source))
                added += DB.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
        DB.commit()
    return added


def db_pool_counts() -> dict:
    with DB_LOCK:
        nowts = now()
        pool_total = DB.execute("SELECT COUNT(*) FROM pool WHERE status='pool'").fetchone()[0]
        busy = DB.execute(
            "SELECT COUNT(*) FROM pool WHERE status='pool' AND claimed_by IS NOT NULL AND claimed_ts>?",
            (nowts - CLAIM_TTL,)).fetchone()[0]
        arch_total = DB.execute("SELECT COUNT(*) FROM pool WHERE status='archive'").fetchone()[0]
    return {"pool": {"total": pool_total, "free": pool_total - busy, "busy": busy},
            "archive": {"total": arch_total}}


def db_pool_entries(status: str, limit: int = 500) -> list:
    with DB_LOCK:
        rows = DB.execute(
            "SELECT id, cookie, nick, pass, claimed_by, claimed_ts, added_ts, source "
            "FROM pool WHERE status=? ORDER BY id LIMIT ?", (status, limit)).fetchall()
    return [{"id": r[0], "cookie": r[1], "nick": r[2], "pass": r[3],
             "claimed_by": r[4], "claimed_ts": r[5], "added_ts": r[6], "source": r[7]}
            for r in rows]


def db_pool_claim(device_id: str, n: int, status: str = "pool") -> list:
    """🔒 Атомарная бронь n кук (сначала продлеваем свои живые брони)."""
    got = []
    with DB_LOCK:
        nowts = now()
        mine = DB.execute(
            "SELECT id, cookie, nick, pass FROM pool WHERE status=? AND claimed_by=? AND claimed_ts>? "
            "ORDER BY id LIMIT ?", (status, device_id, nowts - CLAIM_TTL, n)).fetchall()
        for r in mine:
            DB.execute("UPDATE pool SET claimed_ts=? WHERE id=?", (nowts, r[0]))
            got.append({"id": r[0], "cookie": r[1], "nick": r[2], "pass": r[3]})
        if len(got) < n:
            free = DB.execute(
                "SELECT id, cookie, nick, pass FROM pool WHERE status=? "
                "AND (claimed_by IS NULL OR claimed_by='' OR claimed_ts<=?) "
                "ORDER BY id LIMIT ?",
                (status, nowts - CLAIM_TTL, n - len(got))).fetchall()
            for r in free:
                DB.execute("UPDATE pool SET claimed_by=?, claimed_ts=? WHERE id=?",
                           (device_id, nowts, r[0]))
                got.append({"id": r[0], "cookie": r[1], "nick": r[2], "pass": r[3]})
        DB.commit()
    return got


def db_pool_report(device_id: str, used: list, dead: list, released: list) -> dict:
    """Отчёт телефона: used → в архив (можно поднять позже), dead → удалить,
    released → снять бронь (не понадобились)."""
    with DB_LOCK:
        for c in used or []:
            DB.execute("UPDATE pool SET status='archive', claimed_by=NULL, claimed_ts=NULL "
                       "WHERE cookie=?", (c,))
        for c in dead or []:
            DB.execute("DELETE FROM pool WHERE cookie=?", (c,))
        for c in released or []:
            DB.execute("UPDATE pool SET claimed_by=NULL, claimed_ts=NULL "
                       "WHERE cookie=? AND claimed_by=?", (c, device_id))
        DB.commit()
    return {"ok": True, "used": len(used or []), "dead": len(dead or []),
            "released": len(released or [])}


def db_pool_delete(ids: list) -> int:
    with DB_LOCK:
        n = 0
        for i in ids:
            DB.execute("DELETE FROM pool WHERE id=?", (int(i),))
            n += DB.execute("SELECT changes()").fetchone()[0]
        DB.commit()
    return n


def db_pool_move(ids: list, to: str) -> int:
    if to not in ("pool", "archive"):
        raise HTTPException(400, "to must be pool|archive")
    with DB_LOCK:
        n = 0
        for i in ids:
            DB.execute("UPDATE pool SET status=?, claimed_by=NULL, claimed_ts=NULL WHERE id=?",
                       (to, int(i),))
            n += DB.execute("SELECT changes()").fetchone()[0]
        DB.commit()
    return n


@app.get("/api/pool")
async def api_pool_get():
    return {"counts": db_pool_counts(),
            "pool": db_pool_entries("pool"),
            "archive": db_pool_entries("archive")}


@app.post("/api/pool/add")
async def api_pool_add(body: dict):
    entries = parse_pool_text(body.get("text") or "")
    if not entries:
        raise HTTPException(400, "куки не распознаны (нужно nick:/pass:/.ROBLOSECURITY=... или токены построчно)")
    status = "archive" if body.get("to") == "archive" else "pool"
    added = db_pool_add(entries, status=status, source=body.get("source") or "dashboard")
    return {"ok": True, "added": added, "counts": db_pool_counts()}


@app.post("/api/pool/delete")
async def api_pool_delete(body: dict):
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "no ids")
    return {"ok": True, "deleted": db_pool_delete(ids)}


@app.post("/api/pool/move")
async def api_pool_move(body: dict):
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "no ids")
    return {"ok": True, "moved": db_pool_move(ids, body.get("to") or "archive")}


@app.post("/api/pool/claim")
async def api_pool_claim(body: dict):
    """Телефон бронирует куки: {"device_id","n","from":"pool"|"archive"}"""
    did = str(body.get("device_id") or "")
    n = min(max(int(body.get("n") or 0), 0), 50)
    if not did or n <= 0:
        raise HTTPException(400, "need device_id and n")
    status = "archive" if body.get("from") == "archive" else "pool"
    got = db_pool_claim(did, n, status=status)
    log(f"[🍪] {did}: claim {len(got)}/{n} из {status}")
    return {"ok": True, "got": got, "counts": db_pool_counts()}


@app.post("/api/pool/report")
async def api_pool_report(body: dict):
    did = str(body.get("device_id") or "?")
    r = db_pool_report(did, body.get("used"), body.get("dead"), body.get("released"))
    log(f"[🍪] {did}: report used={r['used']} dead={r['dead']} released={r['released']}")
    return r


# ============================================================
# ⏰ РАСПИСАНИЕ (v0.6): рега ежедневно + сбор урожая по времени МСК
# ============================================================
# Фармеры = ВСЕ онлайн-устройства КРОМЕ сборщиков (рекомендуемые имена "0".."29",
# но подходит любой device_id — и phone_xxxxxx от bootstrap тоже).
# Сборщики: device_id = "collector-1/2/3"
# Сбор: 2 пачки × batch_minutes (по умолчанию 20 мин) — всего 40 мин.
# Попытка дня сгорает только если запуск РЕАЛЬНО начался; если устройств не было
# онлайн — планируемщик повторяет попытку в течение CATCHUP_MIN после времени.

SCHEDULE_FILE = BASE_DIR / "schedule.json"
SCHEDULE_STATE = BASE_DIR / "schedule_state.json"
MSK = timezone(timedelta(hours=3))          # Europe/Moscow (без переходов)
CATCHUP_MIN = 120                            # сколько минут после планового времени догоняем

DEFAULT_SCHEDULE = {
    "enabled": True,
    "rega_time": "03:00",            # МСК — авторегистрация новых акков ежедневно
    "rega_enabled": False,           # 🛡 v0.7: рега акков ВЫКЛЮЧЕНА (безопасный режим,
                                     #         чтобы случайно не потерять акки с лутом)
    "harvest_time": "20:00",         # МСК — сбор урожая
    "batch_minutes": 20,             # 1 пачка = 20 мин, всего 2 пачки = 40 мин
    "cookie_check_interval_min": 30, # проверка кук на всех фармерах
    "rega_target": 5,                # 1 телефон = 5 акков
    "harvest_place_id": "",          # пусто → телефон использует свой PLACE_ID
}


def load_schedule() -> dict:
    cfg = dict(DEFAULT_SCHEDULE)
    try:
        cfg.update(json.loads(SCHEDULE_FILE.read_text()))
    except Exception:
        pass
    return cfg


def save_schedule(cfg: dict):
    SCHEDULE_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))


def load_sched_state() -> dict:
    try:
        return json.loads(SCHEDULE_STATE.read_text())
    except Exception:
        return {"last_rega": "", "last_harvest": "", "rega_pending": [],
                "rega_started": 0, "last_check": 0}


def save_sched_state(st: dict):
    tmp = SCHEDULE_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False))
    tmp.replace(SCHEDULE_STATE)


def farmer_num(did: str):
    """device_id "0".."29" → номер фармера, иначе None"""
    return int(did) if did.isdigit() else None


def device_online(did: str) -> bool:
    d = devices.get(did)
    return bool(d and now() - d["last_seen"] < 90)


def is_collector(did: str) -> bool:
    return did.startswith("collector-")


def _farm_sort_key(d: str):
    n = farmer_num(d)
    return (0, n, "") if n is not None else (1, 0, d)


def farmers_online() -> list:
    """ВСЕ онлайн-устройства кроме сборщиков и анонимов.
    Раньше требовались ЧИСТО ЦИФРОВЫЕ device_id ("0".."29"), а bootstrap выдаёт
    phone_xxxxxx → фармеров было 0 всегда, и весь блок расписания молча бездействовал."""
    return sorted(
        [did for did in devices
         if device_online(did) and not is_collector(did) and not did.startswith("anon_")],
        key=_farm_sort_key)


def farmers_total() -> list:
    """Все известные фармеры (включая офлайн) — для «онлайн X/Y» в дашборде"""
    return sorted([did for did in devices
                   if not is_collector(did) and not did.startswith("anon_")],
                  key=_farm_sort_key)


def collectors_online() -> list:
    return sorted([did for did in devices if is_collector(did) and device_online(did)])


def collectors_total() -> list:
    return sorted([did for did in devices if is_collector(did)])


async def send_task(did: str, task: str, payload: dict = None):
    d = devices.get(did)
    if not d:
        return None
    task_id = f"t_{secrets.token_hex(4)}"
    await d["queue"].put({"type": "task", "task": task, "payload": payload or {},
                          "task_id": task_id})
    remember_result(task_id, "sent", did)
    return task_id


async def orchestrate_rega():
    """Рега на всех онлайн-фармерах: farm ⏹ → пауза → rega.start.
    Когда телефон закончит, он сам поднимет фарм (watchdog) + пришлёт rega.done.
    День (last_rega) помечается ТОЛЬКО если запуск реально начался — иначе
    попытка не сгорает и планировщик повторит в течение catchup-окна.
    🛡 v0.7: если rega_enabled=false — отказ БЕЗ запуска (безопасный режим:
    чтобы случайно не удалить/не перезаписать акки с лутом)."""
    cfg = load_schedule()
    if not cfg.get("rega_enabled", False):
        log("[🆕] Рега ОТКЛЮЧЕНА (rega_enabled=false) — запуск заблокирован (безопасный режим)")
        return {"sent": [], "note": "рега отключена (rega_enabled=false)"}
    farmers = farmers_online()
    if not farmers:
        log("[🆕] Рега: нет онлайн-фармеров — день НЕ помечен, попробуем снова")
        return {"sent": []}
    st = load_sched_state()
    st["rega_pending"] = farmers
    st["rega_started"] = now()
    st["last_rega"] = datetime.now(MSK).strftime("%Y-%m-%d")
    save_sched_state(st)
    log(f"[🆕] Рега: farm ⏹ на {len(farmers)}: {', '.join(farmers)}")
    for did in farmers:
        await send_task(did, "service.stop", {"name": "farm"})
    await asyncio.sleep(30)                    # фарм успевает остановиться и закрыть роблоксы
    sent = []
    for did in farmers:
        tid = await send_task(did, "rega.start", {"target": cfg.get("rega_target", 5)})
        if tid:
            sent.append(did)
    log(f"[🆕] Рега запущена на {len(sent)}: {', '.join(sent)}")
    return {"sent": sent}


_HARVEST_RUNNING = False   # 🌾 v0.7: True пока идёт harvest_flow (cookie.check ждёт)


async def harvest_flow() -> bool:
    """🌾 Сбор урожая v2 (безопасный трейд): сборщики на всё окно (40 мин +
    90с head-start на байпас/выход в приватки), фармеры 2 пачками по 20 мин.
    День (last_harvest) помечается ТОЛЬКО если запуск реально начался.
    🛡 Сборщики — ОТДЕЛЬНЫЕ телефоны collector-* (сервис collector, скрипт
    bank.py): их акки принимают трейды. Если сборщиков нет — сбор всё равно
    идёт: фармеры зайдут в приватки, treid.lua сам будет ждать цели — ЛУТ НЕ ТЕРЯЕТСЯ."""
    global _HARVEST_RUNNING
    cfg = load_schedule()
    mins = max(1, int(cfg.get("batch_minutes", 20)))
    place = cfg.get("harvest_place_id") or ""
    farmers = farmers_online()
    collectors = collectors_online()
    if not farmers and not collectors:
        log("[🌾] Сбор: нет устройств — день НЕ помечен, попробуем снова")
        return False
    st = load_sched_state()
    st["last_harvest"] = datetime.now(MSK).strftime("%Y-%m-%d")
    save_sched_state(st)
    mid = (len(farmers) + 1) // 2               # нечётное число → лишний в пачке 1 (старт сразу)
    b1, b2 = farmers[:mid], farmers[mid:]
    log(f"[🌾] Сбор {mins}+{mins} мин: пачка1={b1 or '—'} | пачка2={b2 or '—'} | сборщики={collectors}")
    if not collectors:
        log("[🌾] ⚠️ Сборщиков (collector-*) нет онлайн — фармеры всё равно выйдут в приватки, "
            "трейд будет ждать целей (безопасно, лут остаётся у фармеров)")
    _HARVEST_RUNNING = True
    try:
        for did in collectors:
            # +2 мин запаса: окно сборщика покрывает head-start + обе пачки
            await send_task(did, "harvest.start", {"minutes": mins * 2 + 2, "place_id": place})
        if collectors:
            log("[🌾] Сборщикам 90с head-start (байпас + выход в приватки) — потом пачка 1")
            await asyncio.sleep(90)
        for did in b1:
            await send_task(did, "harvest.start", {"minutes": mins, "place_id": place})
        await asyncio.sleep(mins * 60)
        log("[🌾] Сбор: пачка 2")
        for did in b2:
            await send_task(did, "harvest.start", {"minutes": mins, "place_id": place})
        await asyncio.sleep(mins * 60)
        for did in collectors:
            await send_task(did, "harvest.stop", {})
        for did in farmers:
            await send_task(did, "harvest.stop", {})
        log("[🌾] Сбор завершён — фарм продолжает обычный цикл")
    finally:
        _HARVEST_RUNNING = False
    return True


def _valid_hhmm(hhmm: str) -> bool:
    """Строго ЧЧ:ММ (00-23:00-59). Раньше проходило «25:99» и расписание
    молча никогда не срабатывало."""
    try:
        h, m = map(int, str(hhmm).split(":"))
        return 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return False


def _hhmm_passed(now_msk: datetime, hhmm: str) -> bool:
    if not _valid_hhmm(hhmm):
        return False
    h, m = map(int, str(hhmm).split(":"))
    return (now_msk.hour, now_msk.minute) >= (h, m)


def _within_catchup(now_msk: datetime, hhmm: str) -> bool:
    if not _valid_hhmm(hhmm):
        return False
    h, m = map(int, str(hhmm).split(":"))
    delta = (now_msk.hour * 60 + now_msk.minute) - (h * 60 + m)
    return 0 <= delta <= CATCHUP_MIN


async def schedule_loop():
    log("[⏰] Планировщик запущен (рега/сбор/проверка кук, время МСК)")
    while True:
        try:
            cfg = load_schedule()
            if cfg.get("enabled"):
                now_msk = datetime.now(MSK)
                today = now_msk.strftime("%Y-%m-%d")
                st = load_sched_state()

                if st.get("rega_pending") and now() - st.get("rega_started", 0) > 4 * 3600:
                    log(f"[🆕] Рега висит >4ч — принудительно farm ▶: {st['rega_pending']}")
                    for did in st["rega_pending"]:
                        await send_task(did, "service.start", {"name": "farm"})
                    # перечитываем state перед записью — пока шли send_task,
                    # ws-обработчик мог обновить rega_pending (гонка состояний)
                    st2 = load_sched_state()
                    st2["rega_pending"] = []
                    save_sched_state(st2)

                # 🛡 v0.7: рега работает ТОЛЬКО при rega_enabled=true (тумблер на дашборде)
                if (cfg.get("rega_enabled", False)
                        and _hhmm_passed(now_msk, cfg.get("rega_time", "03:00"))
                        and _within_catchup(now_msk, cfg.get("rega_time", "03:00"))
                        and st.get("last_rega") != today
                        and not st.get("rega_pending")):
                    spawn_bg(orchestrate_rega())

                if (_hhmm_passed(now_msk, cfg.get("harvest_time", "20:00"))
                        and _within_catchup(now_msk, cfg.get("harvest_time", "20:00"))
                        and st.get("last_harvest") != today):
                    spawn_bg(harvest_flow())

                if not st.get("rega_pending") and not _HARVEST_RUNNING:
                    # 🛡 v0.7: во время активного сбора проверку кук НЕ шлём —
                    # check перезапускает клоны и мешает трейду
                    interval_min = max(5, int(cfg.get("cookie_check_interval_min", 30)))
                    if now() - st.get("last_check", 0) >= interval_min * 60:
                        st["last_check"] = now()
                        save_sched_state(st)
                        for did in farmers_online():
                            await send_task(did, "cookie.check", {})
        except Exception as e:
            log(f"[⏰] schedule error: {e}")
        await asyncio.sleep(30)


@app.on_event("startup")
async def _startup():
    spawn_bg(schedule_loop())


@app.get("/api/schedule")
async def api_schedule_get():
    return {"schedule": load_schedule(), "state": load_sched_state(),
            "farmers_online": farmers_online(), "collectors_online": collectors_online(),
            "farmers_total": farmers_total(), "collectors_total": collectors_total()}


@app.post("/api/schedule")
async def api_schedule_set(body: dict):
    cfg = load_schedule()
    old_rega = bool(cfg.get("rega_enabled", False))
    for k in DEFAULT_SCHEDULE:
        if k in body:
            cfg[k] = body[k]
    if "rega_time" in body or "harvest_time" in body:
        for k in ("rega_time", "harvest_time"):
            if k in body and not _valid_hhmm(body[k]):
                raise HTTPException(400, f"{k} должен быть ЧЧ:ММ (00-23:00-59), например 03:00")
    save_schedule(cfg)
    log(f"[⏰] Расписание обновлено: {cfg}")
    # 🛡 v0.23: rega_enabled изменился через /api/schedule (панель шлёт весь
    # конфиг целиком) → рассылаем rega.switch, иначе телефоны не узнают и
    # rega_switch.json разойдётся с сервером (та самая «написано выключено,
    # а рега работает»). Раньше флаг менялся молча — hello-sync догонял бы
    # только при переподключении телефона.
    new_rega = bool(cfg.get("rega_enabled", False))
    if new_rega != old_rega:
        sent = []
        for did in list(devices.keys()):
            if did.startswith("anon_") or not device_online(did):
                continue
            if await send_task(did, "rega.switch", {"enabled": new_rega,
                                                    "source": "schedule-save"}):
                sent.append(did)
        log(f"[🛡] rega_enabled изменён через /api/schedule: {old_rega} → {new_rega} "
            f"— rega.switch отправлен: {sent or '—'}")
    return {"ok": True, "schedule": cfg}


@app.post("/api/rega/start")
async def api_rega_now():
    """Кнопка «Рега сейчас» — вне расписания. Честный ответ: если фармеров
    онлайн нет — ok:false и список, а не безликое «запускается».
    🛡 v0.7: при rega_enabled=false — отказ (безопасный режим)."""
    if not load_schedule().get("rega_enabled", False):
        log("[🆕] Рега сейчас: ОТКЛЮЧЕНА (rega_enabled=false)")
        return {"ok": False, "farmers": [], "farmers_total": farmers_total(),
                "note": "🛡 рега ОТКЛЮЧЕНА (безопасный режим — акки с лутом защищены). "
                        "Включи тумблером «🆕 Рега акков» в блоке расписания"}
    farmers = farmers_online()
    if not farmers:
        log("[🆕] Рега сейчас: нет онлайн-фармеров")
        return {"ok": False, "farmers": [], "farmers_total": farmers_total(),
                "note": "нет онлайн-фармеров — некому запускать регу"}
    spawn_bg(orchestrate_rega())
    return {"ok": True, "farmers": farmers,
            "note": "рега запускается (farm ⏹ → 30с → rega.start)"}


@app.post("/api/rega/switch")
async def api_rega_switch(body: dict):
    """🛡 v0.7: тумблер регы акков. Сохраняет rega_enabled в расписании и шлёт
    rega.switch всем онлайн-телефонам (клиент пишет info/rega_switch.json —
    фарм-гейт и кнопка «Рег акков» на телефоне подчиняются). Офлайн-телефоны
    догонят состояние при следующем hello (сервер шлёт rega.switch сам)."""
    enabled = bool(body.get("enabled"))
    cfg = load_schedule()
    cfg["rega_enabled"] = enabled
    save_schedule(cfg)
    sent = []
    for did in list(devices.keys()):
        if did.startswith("anon_") or not device_online(did):
            continue
        if await send_task(did, "rega.switch", {"enabled": enabled}):
            sent.append(did)
    log(f"[🛡] Рега акков {'ВКЛЮЧЕНА' if enabled else 'ОТКЛЮЧЕНА (безопасный режим)'} "
        f"— rega.switch отправлен: {sent or '—'} (офлайн догонят при hello)")
    return {"ok": True, "rega_enabled": enabled, "sent": sent,
            "note": ("рега ВКЛЮЧЕНА — телефоны снова регистрируют акки"
                     if enabled else
                     "🛡 рега ОТКЛЮЧЕНА — авторегистрация и замена кук остановлены, "
                     "акки с лутом защищены")}


@app.post("/api/harvest/start")
async def api_harvest_now():
    """Кнопка «Сбор сейчас» — вне расписания. last_harvest ставит сам
    harvest_flow при реальном старте — клик «впустую» не сжигает день"""
    farmers = farmers_online()
    collectors = collectors_online()
    if not farmers and not collectors:
        log("[🌾] Сбор сейчас: нет онлайн-устройств")
        return {"ok": False, "farmers": [], "collectors": [],
                "farmers_total": farmers_total(), "collectors_total": collectors_total(),
                "note": "нет онлайн-устройств — некому запускать сбор"}
    spawn_bg(harvest_flow())
    return {"ok": True, "farmers": farmers, "collectors": collectors,
            "note": "сбор запускается (2 пачки)"}


@app.post("/api/cookie/check")
async def api_cookie_check():
    farmers = farmers_online()
    for did in farmers:
        await send_task(did, "cookie.check", {})
    return {"ok": True, "sent": farmers}


# ---------- Дашборд ----------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    if not DASHBOARD_FILE.is_file():
        return HTMLResponse("<h1>dashboard.html не найден в ~/farm-server/</h1>", status_code=500)
    return HTMLResponse(DASHBOARD_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
