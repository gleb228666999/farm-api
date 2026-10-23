"""Фейковый телефон для E2E-теста панели.

ОДИН поток делает ВСЕ ws.send (периодика кладёт сообщения в очередь outbox).
Это обходит зависания параллельных send в websockets 16.
"""
import faulthandler
import json
import os
import queue
import signal
import threading
import time

faulthandler.register(signal.SIGUSR1)

from websockets.sync.client import connect

WS = "ws://127.0.0.1:8000/ws"
DEVICE_ID = os.environ.get("MOCK_DEVICE_ID", "0")

EVENTS = [
    {"id": "ev_test_1", "ts": time.time(), "type": "farm.start", "info": {"pid": 123}},
    {"id": "ev_test_2", "ts": time.time(), "type": "bypass.ok", "info": {"key_age_h": 0.1}},
    {"id": "ev_test_3", "ts": time.time(), "type": "farm.cycle", "info": {"packages": 4}},
]

outbox: "queue.Queue[dict]" = queue.Queue()


def make_result(task_id: str, task: str, payload: dict) -> dict:
    data = {"ok": True, "task": task, "echo": payload}
    if task == "ping":
        data = {"pong": True, "uptime_sec": 42}
    elif task == "service.status":
        data = {"farm": {"running": True, "pid": 555, "desired": "running"},
                "rega": {"running": False, "pid": None, "desired": "stopped"},
                "demo": {"running": False, "pid": None, "desired": "stopped"}}
    elif task == "exec":
        data = {"ok": True, "code": 0, "output": "mock exec output\n"}
    elif task == "update":
        data = {"ok": True, "updated": [], "restart_needed": False}
    elif task == "file.read":
        data = {"ok": True, "content": "line1\nline2\nmock log tail"}
    elif task == "restart":
        data = {"ok": True, "note": "supervisor поднимет"}
    elif task == "halt":
        data = {"ok": True, "note": "полная остановка"}
    elif task == "apk.update":
        data = {"ok": True, "updated_any": False, "reboot_now": False}
    elif task == "service.start":
        data = {"ok": True, "pid": 777}
    elif task == "service.stop":
        data = {"ok": True}
    elif task == "harvest.start":
        data = {"ok": True, "until_ts": time.time() + 1200, "place_id": ""}
    elif task == "harvest.stop":
        data = {"ok": True, "note": "фарм вернётся к обычному циклу"}
    elif task == "rega.start":
        data = {"ok": True, "note": "рега запущена"}
    elif task == "rega.switch":
        data = {"ok": True, "rega_enabled": bool(payload.get("enabled")),
                "note": "kill-switch регы обновлён (mock)"}
    elif task == "bypass.run":
        data = {"ok": True, "farm_was_running": True, "farm_started": False,
                "collector_running": False,
                "ts": time.time(), "source": (payload.get("source") or "dashboard"),
                "note": "фарм выполнит полный байпас v18.8 ≤30с; события bypass.*"}
    elif task == "cookie.check":
        data = {"ok": True, "note": "проверка запущена в фоне"}
    return {"type": "result", "device_id": DEVICE_ID, "task_id": task_id, "data": data}


def periodic():
    time.sleep(2)
    outbox.put({"type": "events", "device_id": DEVICE_ID, "events": EVENTS})
    while True:
        time.sleep(10)
        outbox.put({"type": "heartbeat", "device_id": DEVICE_ID, "battery": 87,
                    "farm": {"last_key_time": time.time() - 3600}})


def main():
    ws = connect(WS)
    print("[mock] connected", flush=True)
    ws.send(json.dumps({
        "type": "hello", "device_id": DEVICE_ID, "client_version": "0.14",
        "info": {"android": "14", "model": "Pixel Test", "battery": 87},
    }))
    print("[mock] >> hello", flush=True)

    threading.Thread(target=periodic, daemon=True).start()

    while True:
        raw = None
        try:
            raw = ws.recv(0.5)
        except TimeoutError:
            pass
        except Exception as e:
            print(f"[mock] recv err: {e}", flush=True)
            return
        if raw:
            print(f"[mock] << {raw[:90]}", flush=True)
            try:
                msg = json.loads(raw)
            except Exception:
                msg = None
            if isinstance(msg, dict) and msg.get("type") == "task":
                reply = make_result(msg.get("task_id", "?"), msg.get("task", "?"),
                                    msg.get("payload") or {})
                ws.send(json.dumps(reply))
                print(f"[mock] >> result {reply['task_id']}", flush=True)
        while not outbox.empty():
            obj = outbox.get()
            ws.send(json.dumps(obj))
            print(f"[mock] >> {obj.get('type')}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
