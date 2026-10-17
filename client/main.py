"""
🤖 Farm Client v0.6
- v0.4: связь, exec, сервисы, watchdog, update по воздуху
- v0.5: неубиваемость по схеме v7.2: client.pid для supervisor/стража,
        selfheal (сам переустанавливает неубиваемость), halt/restart,
        абсолютные пути (работает даже если PATH побит root-стражем)
- v0.6: ЭТАП 1 — фарм v16.2 как сервис (services/farm/main.py),
        манифест services.json + demo + farm, кнопки фарма в дашборде
"""
import sys
import os
import json
import time
import signal
import hashlib
import asyncio
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
TERMUX_BIN = "/data/data/com.termux/files/usr/bin"
ENV = {**os.environ, "PATH": f"{TERMUX_BIN}:{os.environ.get('PATH', '')}"}

if not (BASE / "core" / "connection.py").exists() or not (BASE / "config.json").exists():
    print("❌ Установка неполная. Запусти: python bootstrap.py")
    sys.exit(1)

from core.connection import Connection
from core.process_manager import ProcessManager

VERSION = "0.6"
START = time.time()
CONFIG = json.loads((BASE / "config.json").read_text())

WS_URL = CONFIG.get("ws_url") or (
    CONFIG["server_url"].replace("http://", "ws://")
                         .replace("https://", "wss://").rstrip("/") + "/ws"
)

# pid-файл: по нему supervisor и root-страж видят, что клиент жив
try:
    (BASE / "info").mkdir(parents=True, exist_ok=True)
    (BASE / "info" / "client.pid").write_text(str(os.getpid()))
except Exception:
    pass

PM = ProcessManager(BASE)

_bg = set()
def spawn(coro):
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)
    return t


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def sh(cmd: str) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return "?"


def get_battery():
    try:
        out = subprocess.run([f"{TERMUX_BIN}/termux-battery-status"],
                             capture_output=True, text=True, timeout=3).stdout
        return json.loads(out).get("percentage")
    except Exception:
        return None


def get_device_info() -> dict:
    return {
        "android": sh("getprop ro.build.version.release"),
        "model": sh("getprop ro.product.model"),
        "battery": get_battery(),
    }


# ==========================
# 🛡 САМОЛЕЧЕНИЕ (как keepalive_install в v7.2)
# ==========================

def supervisor_running() -> bool:
    try:
        for d in Path("/proc").iterdir():
            if d.name.isdigit():
                try:
                    cl = (d / "cmdline").read_bytes().decode(errors="replace")
                except Exception:
                    continue
                if "supervisor.sh" in cl.replace("\x00", " "):
                    return True
    except Exception:
        pass
    return False


def selfheal():
    """Клиент при старте сам ставит неубиваемость, если её нет/она старая.
    setup при этом может убить нас — это нормально: supervisor поднимет."""
    try:
        marker = BASE / "info" / "setup_done.json"
        v = 0
        if marker.exists():
            try:
                v = json.loads(marker.read_text()).get("v", 0)
            except Exception:
                pass
        if v == 5 and supervisor_running():
            return
        log("🛡 selfheal: ставлю неубиваемость (setup.py)...")
        subprocess.run([sys.executable, str(BASE / "setup.py")],
                       env=ENV, timeout=240,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("🛡 selfheal: готово")
    except Exception as e:
        log(f"🛡 selfheal error: {e}")


# ==========================
# ЗАДАЧИ ОТ СЕРВЕРА
# ==========================

async def task_exec(payload: dict) -> dict:
    cmd = payload.get("command", "")
    timeout = min(float(payload.get("timeout", 30)), 180)
    if not cmd:
        return {"ok": False, "error": "empty command"}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(BASE), env=ENV,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return {"ok": proc.returncode == 0, "code": proc.returncode,
                "output": out.decode(errors="replace")[-4000:]}
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try: proc.kill()
            except Exception: pass
        return {"ok": False, "error": f"timeout ({timeout}s), процесс убит"}


def task_file_read(payload: dict) -> dict:
    rel = str(payload.get("path", ""))
    tail = min(int(payload.get("tail", 3000)), 20000)
    if not rel:
        return {"ok": False, "error": "no path"}
    p = (BASE / rel).resolve()
    try:
        p.relative_to(BASE.resolve())
    except ValueError:
        return {"ok": False, "error": "path outside farm/"}
    if p.is_file():
        return {"ok": True,
                "content": p.read_bytes()[-tail:].decode(errors="replace")}
    return {"ok": False, "error": "not found"}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"FarmClient/{VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def task_update(payload: dict) -> dict:
    base = CONFIG.get("server_url") or WS_URL.replace("ws://", "http://") \
        .replace("wss://", "https://").rsplit("/ws", 1)[0]
    manifest = json.loads(http_get(f"{base}/client/manifest"))
    changed = []
    for f in manifest["files"]:
        dest = BASE / f["path"]
        cur = hashlib.sha256(dest.read_bytes()).hexdigest() if dest.is_file() else None
        if cur == f["sha256"]:
            continue
        q = urllib.parse.quote(f["path"], safe="/")
        content = http_get(f"{base}/client/file?path={q}")
        if hashlib.sha256(content).hexdigest() != f["sha256"]:
            return {"ok": False, "error": f"hash mismatch: {f['path']}"}
        if f["path"].endswith(".py"):
            try:
                compile(content.decode("utf-8"), f["path"], "exec")
            except SyntaxError as e:
                return {"ok": False, "error": f"syntax error in {f['path']}: {e}"}
        changed.append((f["path"], content))
    for path, content in changed:
        dest = BASE / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, dest)
    return {"ok": True, "updated": [p for p, _ in changed],
            "restart_needed": bool(changed)}


TASKS_SYNC = {
    "service.start":  lambda p: PM.start(p.get("name", "")),
    "service.stop":   lambda p: PM.stop(p.get("name", "")),
    "service.status": lambda p: PM.status(),
    "file.read":      task_file_read,
}


async def handle_task(conn: Connection, msg: dict):
    task = msg.get("task")
    payload = msg.get("payload") or {}
    task_id = msg.get("task_id")
    log(f"📨 Задача: {task} (id={task_id})")
    t0 = time.time()

    async def reply(data):
        try:
            await conn.send({"type": "result", "device_id": CONFIG["device_id"],
                             "task_id": task_id, "data": data,
                             "took_ms": round((time.time() - t0) * 1000)})
            log(f"📤 {task_id} done")
        except Exception as e:
            log(f"❌ не смог отправить результат {task_id}: {e}")

    # --- задачи, которые убивают нас: сначала ответ, потом действие ---

    if task == "restart":
        await reply({"ok": True, "note": "supervisor поднимет через ~60с"})
        await asyncio.sleep(1)
        os._exit(0)

    elif task == "halt":
        script = BASE / "farm_stop.sh"
        if not script.exists():
            await reply({"ok": False, "error": "нет farm_stop.sh — сделай update"})
        else:
            await reply({"ok": True, "note": "полная остановка: клиент+supervisor+страж"})
            await asyncio.sleep(1)
            subprocess.Popen(["sh", str(script)], env=ENV,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        return

    elif task == "update":
        data = await asyncio.to_thread(task_update, payload)
        await reply(data)
        if data.get("restart_needed"):
            log("♻️ обновлено, перезапуск (supervisor поднимет)")
            await asyncio.sleep(2)
            os._exit(0)
        return

    # --- обычные задачи ---

    if task == "ping":
        data = {"pong": True, "uptime_sec": round(time.time() - START)}
    elif task == "exec":
        data = await task_exec(payload)
    elif task in TASKS_SYNC:
        data = await asyncio.to_thread(TASKS_SYNC[task], payload)
    else:
        data = {"error": f"unknown task: {task}"}
    await reply(data)


# ==========================
# ЛУПЫ
# ==========================

async def heartbeat_loop(conn, interval):
    while True:
        await conn.send({
            "type": "heartbeat",
            "device_id": CONFIG["device_id"],
            "battery": get_battery(),
            "uptime": round(time.time() - START),
        })
        await asyncio.sleep(interval)


async def watchdog_loop():
    while True:
        await asyncio.sleep(10)
        try:
            restarted = await asyncio.to_thread(PM.reanimate)
            for name in restarted:
                log(f"🔄 watchdog: перезапустил '{name}'")
        except Exception as e:
            log(f"❌ watchdog error: {e}")


async def listen_loop(conn):
    while True:
        msg = await conn.recv()
        t = msg.get("type")
        if t == "welcome":
            log(f"👋 Сервер: online={msg.get('online')}")
        elif t == "heartbeat_ack":
            pass
        elif t == "task":
            spawn(handle_task(conn, msg))
        else:
            log(f"❓ {t}: {json.dumps(msg, ensure_ascii=False)}")


async def main():
    log(f"🚀 Farm Client v{VERSION} | device_id={CONFIG['device_id']}")
    log(f"   Сервер: {WS_URL}")

    selfheal()   # 🛡 может убить нас при миграции — тогда supervisor поднимет уже новое

    started = await asyncio.to_thread(PM.autostart)
    if started:
        log(f"▶️ Автостарт: {', '.join(started)}")

    conn = Connection(WS_URL)

    while True:
        try:
            log("🔗 Подключаюсь...")
            await conn.connect()
            log("✅ Подключен!")
        except Exception as e:
            delay = conn.next_delay()
            log(f"❌ Не подключился: {e} → жду {delay}с")
            await asyncio.sleep(delay)
            continue

        try:
            await conn.send({
                "type": "hello",
                "device_id": CONFIG["device_id"],
                "client_version": VERSION,
                "info": get_device_info(),
            })
        except Exception as e:
            log(f"❌ Ошибка hello: {e}")
            continue

        try:
            tasks = [
                asyncio.create_task(listen_loop(conn)),
                asyncio.create_task(heartbeat_loop(conn, CONFIG["heartbeat_interval"])),
                asyncio.create_task(watchdog_loop()),
            ]
            done, pending = await asyncio.wait(tasks,
                                               return_when=asyncio.FIRST_EXCEPTION)
            for t in pending:
                t.cancel()
            for t in done:
                if t.exception():
                    raise t.exception()
        except Exception as e:
            log(f"❌ Связь потеряна: {e}")
            conn.connected = False
            delay = conn.next_delay()
            log(f"   Реконнект через {delay}с...")
            await asyncio.sleep(delay)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Остановлено (сервисы продолжают работать — это норма)")
