#!/usr/bin/env python3
"""
🚜 Farm Server v0.5
- /ws                      телефоны (hello, heartbeat, events, task, result)
- /client/manifest|file    раздача клиента (sha256)
- /bootstrap.py            установщик для телефонов
- /api/devices|send|broadcast|results|update
- /api/events              события фарма из SQLite (этап 2)
- /api/groups              группы устройств (этап 4) + send в группу
- /api/pool                🍪 пул кук на сервере (добавить/удалить/бронь/архив)
- /api/schedule            ⏰ расписание: рега ежедневно + сбор в 20:00 МСК (2×20 мин)
- /                        дашборд (dashboard.html)
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
# ⏰ РАСПИСАНИЕ (v0.5): рега ежедневно + сбор урожая в 20:00 МСК
# ============================================================
# Фармеры: device_id = "0".."29" (0-9 → collector-1, 10-19 → collector-2, 20-29 → collector-3)
# Сборщики: device_id = "collector-1/2/3"
# Сбор: 2 пачки × batch_minutes (по умолчанию 20 мин) — всего 40 мин.

SCHEDULE_FILE = BASE_DIR / "schedule.json"
SCHEDULE_STATE = BASE_DIR / "schedule_state.json"
MSK = timezone(timedelta(hours=3))          # Europe/Moscow (без переходов)
CATCHUP_MIN = 120                            # сколько минут после планового времени догоняем

DEFAULT_SCHEDULE = {
    "enabled": True,
    "rega_time": "03:00",            # МСК — авторегистрация новых акков ежедневно
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


def farmers_online() -> list:
    return sorted([did for did in devices if farmer_num(did) is not None and device_online(did)],
                  key=lambda d: farmer_num(d))


def collectors_online() -> list:
    return sorted([did for did in devices if did.startswith("collector-") and device_online(did)])


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
    Когда телефон закончит, он сам поднимет фарм (watchdog) + пришлёт rega.done."""
    cfg = load_schedule()
    farmers = farmers_online()
    if not farmers:
        log("[🆕] Рега: нет онлайн-фармеров — пропуск")
        return {"sent": []}
    st = load_sched_state()
    st["rega_pending"] = farmers
    st["rega_started"] = now()
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


async def harvest_flow():
    """🌾 Сбор урожая: сборщики на 40 мин, фармеры 2 пачками по 20 мин."""
    cfg = load_schedule()
    mins = max(1, int(cfg.get("batch_minutes", 20)))
    place = cfg.get("harvest_place_id") or ""
    farmers = farmers_online()
    collectors = collectors_online()
    if not farmers and not collectors:
        log("[🌾] Сбор: нет устройств — пропуск")
        return
    mid = (len(farmers) + 1) // 2               # нечётное число → лишний в пачке 1 (старт сразу)
    b1, b2 = farmers[:mid], farmers[mid:]
    log(f"[🌾] Сбор {mins}+{mins} мин: пачка1={b1 or '—'} | пачка2={b2 or '—'} | сборщики={collectors}")
    for did in collectors:
        await send_task(did, "harvest.start", {"minutes": mins * 2, "place_id": place})
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
    log("[🌾] Сбор завершён — farm продолжает обычный цикл")


def _hhmm_passed(now_msk: datetime, hhmm: str) -> bool:
    try:
        h, m = map(int, str(hhmm).split(":"))
    except Exception:
        return False
    return (now_msk.hour, now_msk.minute) >= (h, m)


def _within_catchup(now_msk: datetime, hhmm: str) -> bool:
    try:
        h, m = map(int, str(hhmm).split(":"))
    except Exception:
        return False
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
                    st["rega_pending"] = []
                    save_sched_state(st)

                if (_hhmm_passed(now_msk, cfg.get("rega_time", "03:00"))
                        and _within_catchup(now_msk, cfg.get("rega_time", "03:00"))
                        and st.get("last_rega") != today):
                    st["last_rega"] = today
                    save_sched_state(st)
                    asyncio.create_task(orchestrate_rega())

                if (_hhmm_passed(now_msk, cfg.get("harvest_time", "20:00"))
                        and _within_catchup(now_msk, cfg.get("harvest_time", "20:00"))
                        and st.get("last_harvest") != today):
                    st["last_harvest"] = today
                    save_sched_state(st)
                    asyncio.create_task(harvest_flow())

                if not st.get("rega_pending"):
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
    asyncio.create_task(schedule_loop())


@app.get("/api/schedule")
async def api_schedule_get():
    return {"schedule": load_schedule(), "state": load_sched_state(),
            "farmers_online": farmers_online(), "collectors_online": collectors_online()}


@app.post("/api/schedule")
async def api_schedule_set(body: dict):
    cfg = load_schedule()
    for k in DEFAULT_SCHEDULE:
        if k in body:
            cfg[k] = body[k]
    if "rega_time" in body or "harvest_time" in body:
        for k in ("rega_time", "harvest_time"):
            if k in body and not re.match(r'^\d{1,2}:\d{2}$', str(body[k])):
                raise HTTPException(400, f"{k} должен быть ЧЧ:ММ")
    save_schedule(cfg)
    log(f"[⏰] Расписание обновлено: {cfg}")
    return {"ok": True, "schedule": cfg}


@app.post("/api/rega/start")
async def api_rega_now():
    """Кнопка «Рега сейчас» — вне расписания"""
    asyncio.create_task(orchestrate_rega())
    return {"ok": True, "note": "рега запускается (farm ⏹ → 30с → rega.start)"}


@app.post("/api/harvest/start")
async def api_harvest_now():
    """Кнопка «Сбор сейчас» — вне расписания"""
    st = load_sched_state()
    st["last_harvest"] = datetime.now(MSK).strftime("%Y-%m-%d")
    save_sched_state(st)
    asyncio.create_task(harvest_flow())
    return {"ok": True, "note": "сбор запускается (2 пачки)"}


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
