#!/usr/bin/env python3
"""
🚜 Farm Server v0.3
- /ws                      телефоны (hello, heartbeat, task, result)
- /client/manifest|file    раздача клиента (sha256)
- /bootstrap.py            установщик для телефонов
- /api/devices|send|broadcast|results|update
- /                        дашборд (dashboard.html)
"""
import json
import time
import hashlib
import secrets
import asyncio
from pathlib import Path
from datetime import datetime

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
                await queue.put({"type": "heartbeat_ack", "server_time": now()})

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
    out = []
    for did, d in devices.items():
        out.append({
            "device_id": did,
            "online": now() - d["last_seen"] < 90,
            "last_seen_sec": int(now() - d["last_seen"]),
            "client_version": d.get("client_version"),
            "info": d.get("info", {}),
            "uptime_sec": int(now() - d["connected_at"]),
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


# ---------- Дашборд ----------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    if not DASHBOARD_FILE.is_file():
        return HTMLResponse("<h1>dashboard.html не найден в ~/farm-server/</h1>", status_code=500)
    return HTMLResponse(DASHBOARD_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
