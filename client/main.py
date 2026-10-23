"""
🤖 Farm Client v0.8
- v0.4: связь, exec, сервисы, watchdog, update по воздуху
- v0.5: неубиваемость по схеме v7.2: client.pid для supervisor/стража,
        selfheal (сам переустанавливает неубиваемость), halt/restart,
        абсолютные пути (работает даже если PATH побит root-стражем)
- v0.6: ЭТАП 1 — фарм v16.2 как сервис (services/farm/main.py),
        манифест services.json + demo + farm, кнопки фарма в дашборде
- v0.7: APK-менеджер: задача apk.update — скачать и поставить APK из
        link-apps (github staffere228-alt/apk), при реальном обновлении
        версии — телефон перезагружается ПОСЛЕ отправки результата
- v0.8: ЭТАПЫ 2+4 — события фарма (outbox: core/events.py читает
        info/farm_events.jsonl, шлёт на сервер по events_ack, дубликаты
        отсекает сервер по id) + возраст ключа в heartbeat (farm_state.json);
        группы устройств — на стороне сервера/дашборда, клиенту не нужно
- v0.9: чистая остановка фарма — при farm ⏹ фарм сам закрывает ВСЕ роблоксы
        (com.roblox*) и браузеры до выхода; PM.stop фарма ждёт до 25с (было 10с —
        зачистка не успевала бы); farm_stop.sh (полный стоп) тоже дочищает роблоксы
- v0.10: ФАРМ + СБОР УРОЖАЯ + РЕГА: задачи rega.start (сервис рега:
        авторегистрация по принципам v18.8, пул кук НА СЕРВЕРЕ),
        harvest.start/stop (окно сбора info/harvest_window.json — фарм заходит
        в приватки на время окна), cookie.check (проверка кук, вылетела —
        замена из пула сервера, если пуст — из архива). Исходящие события:
        farm_events.jsonl + rega_events.jsonl
- v0.11: (в сервисах) куки-гейт — фарм не делает байпас/фарм без кук:
        0 сессий → сам запускает авторегистрацию (rega, flock от двойного
        запуска) и ждёт; рега не дала кук — пауза 30 мин и снова
- v0.12: (в сервисах) куки-гейт v2 — гейт смотрит на обе части фермы:
        нет куки на Дельте (байпас не работает) ИЛИ все клоны пустые
        (фармить нечем) → сначала рега; частичная убыль кук регу не поднимает
- v0.13: (в сервисах) ПОЛНЫЙ стоп — farm ⏹ глушит и регу (SIGTERM → 8с →
        SIGKILL + чистка pid-файла); рега при остановке шлёт rega.stop и больше
        НЕ реармит фарм (остановленный фарм больше не встаёт сам); гейт ждёт
        освобождения flock-лока, если спавн рега упал с кодом 99
- v0.14: (в сервисах) рега = 20 попыток (2 подхода × 10) ВСЕГДА, не важно
        удачно или нет — досрочного выхода по достижении цели нет, излишки
        идут в пул; после каждых 10 попыток отдых 15 мин (rate-limit тоже 15)
- v0.15: задача bypass.run — БАЙПАС КАК В v18.8 ПО КНОПКЕ: клиент ставит
        флаг info/bypass_force.json → фарм (services/farm) в ≤30с делает
        ПОЛНЫЙ цикл (Delta → реклама → ZEN-API → ключ → license) БЕЗ рестарта
        сервиса; если фарм не жил — сам запускается и сразу байпасит;
        вылетевшие клоны при фарме И при сборе мониторинг перезапускает в плейс
- v0.16: (в сервисах) байпас — ОРИЕНТАЦИЯ ВСЕГДА ГОРИЗОНТАЛЬНАЯ: все координаты
        байпаса ландшафтные, но поворот ставился ПОСЛЕ клика Get Key в Дельте,
        а Chrome при переходе на сайт сбрасывал его в портрет → клики
        промахивались. Теперь force_landscape() ставит user_rotation=1 +
        ПРОВЕРЯЕТ реальный поворот по dumpsys (3 повтора) на ВСЕХ этапах:
        старт попытки, ДО клика Get Key в Дельте, открытие сайта, перед кликами
        по сайту, чтение ключа; сбросы в портрет из байпаса убраны — ландшафт
        держится от начала до конца
- v0.17: (в сервисах) ГЕЙТ ЖИВОГО АККА ПЕРЕД БАЙПАСОМ: has_session считал
        акком и ПРОТУХШУЮ куку → байпас стартовал вхолостую (без акка Дельта
        не заходит на плейс, 9 попыток в мусор). Теперь read_main_cookie()
        достаёт .ROBLOSECURITY главного Roblox, а _roblox_auth_check()
        проверяет её через users.roblox.com (401 = мертва). Нет живого акка →
        bypass.no_account + bypass.fail ДО попыток; флаг кнопки НЕ тратится —
        рега чинит куки и байпас выполнится сам на следующем проходе
- v0.18: (в сервисах) 4 фикса логики: (1) кнопка байпаса ВО ВРЕМЯ СБОРА
        не работала: монитор возвращал «bypass», флаг не съедался, сбор
        запускался снова → монитор снова видел флаг → вечный круг; теперь
        байпас выполняется сразу и сбор продолжается на остаток окна;
        (2) флаг байпаса: сбой удаления файла = «флаг забран», а файл
        оставался → байпас по кругу без остановки; теперь не удалить =
        не запускать + TTL 12ч для застрявшего флага; (3) livelock
        «рега↔гейт»: починка отчитывалась успехом по НАЛИЧИЮ протухшей
        куки → вечный круг; теперь честная API-проверка + счётчик подряд
        неудач (3 → пауза 2ч, 6 → сброс флага и работа без байпаса — фарм
        клонами не зависит от байпаса); (4) force_landscape в остановке
        мог пробить бюджет 25с (худший случай ≈50с → SIGKILL посреди
        зачистки) — быстрая версия без dumpsys-проверки
- v0.19: (в сервисах) ЗАЩИТА РЕГИ ОТ СЛУЧАЙНЫХ КЛОНОВ: если во время
        регистрации случайно запустился клон Roblox (тап по рабочему
        столу) — он перехватывает фокус и тапы, попытка пропадает.
        Теперь сторож реги закрывает ВСЕ com.roblox* кроме Дельты
        (+ Chrome/браузер) на всех этапах регистрации: старт, перед/
        после каждой попытки, ожидания запуска/экрана/пароля/куки, паузы
        15 мин; попытка продолжается (main сам вернётся вперёд) или
        повторяется следующим заходом. Инъекция кук в клоны и check-режим
        сторожем НЕ трогаются — там клоны запускаются намеренно
- v0.20: 🛡 БЕЗОПАСНЫЙ РЕЖИМ + СБОР-ТРЕЙД (отдельный телефон-сборщик):
        • задача rega.switch {enabled} — kill-switch регы АККОВ: клиент
          пишет info/rega_switch.json (файла нет = ВЫКЛЮЧЕНА — безопасный
          режим по умолчанию, чтобы случайно не потерять акки с лутом);
          сервер присылает переключение при hello и по тумблеру дашборда;
        • rega.start при выключенной реге отказывает (ok:false) —
          авторегистрация и замена кук на этом телефоне не идут;
        • cookie.check отказывает во время активного окна сбора (не мешаем
          трейду — check перезапускает клоны);
        • bypass.run: если на телефоне жив СБОРЩИК (сервис collector) — фарм
          не стартуем, байпас выполнит сборщик (тот же флаг bypass_force);
        • (в сервисах) фарм: СБОР v2 — автоэкзекют на время окна = treid.lua
          (масс-трейд лута целям-сборщикам), приватки ТОЛЬКО из id.txt хозяина
          (кэш), вылетевший клон возвращается НА СВОЙ приватный сервер, после
          окна фарм-скрипт восстанавливается; новый сервис collector (порт из
          bank.py хозяина): автоэкзекют = collet.lua (авто-приём трейдов),
          полный байпас v18.8, те же приватки из id.txt
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
from core.apk_manager import run_apk_update, reboot_phone
from core.events import EventOutbox

VERSION = "0.20"
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
OUTBOX = EventOutbox(BASE)   # события фарма → сервер (этап 2)

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


def get_farm_state() -> dict | None:
    """farm_state.json пишет ТОЛЬКО фарм, клиент читает (для дашборда: возраст ключа)"""
    try:
        return json.loads((BASE / "info" / "farm_state.json").read_text())
    except Exception:
        return None


# ---------- 🛡 kill-switch регы акков (v0.20, безопасный режим) ----------

REGA_SWITCH_FILE = BASE / "info" / "rega_switch.json"


def rega_switch_enabled() -> bool:
    """Включена ли рега акков НА ЭТОМ телефоне. Файл пишет клиент (задача
    rega.switch с сервера — тумблер дашборда и hello-sync). Файла нет =
    ВЫКЛЮЧЕНА: безопасный режим по умолчанию — акки с лутом защищены."""
    try:
        return bool(json.loads(REGA_SWITCH_FILE.read_text()).get("enabled"))
    except Exception:
        return False


def task_rega_switch(payload: dict) -> dict:
    """🛡 Сервер включил/выключил регу акков (тумблер дашборда / hello-sync).
    🆘 v0.23: при ВЫКЛЮЧЕНИИ — убиваем ИДУЩУЮ регу (раньше процесс продолжал
    стирать/регистрировать акки после выключения тумблера — дашборд показывал
    «выключено», а акки банило). Режим check НЕ трогаем — он только чинит куки."""
    enabled = bool(payload.get("enabled"))
    data = {"enabled": enabled, "ts": round(time.time(), 1),
            "source": str(payload.get("source") or "server")}
    tmp = REGA_SWITCH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(REGA_SWITCH_FILE)                       # атомарно
    log(f"🛡 Рега акков {'ВКЛЮЧЕНА' if enabled else 'ОТКЛЮЧЕНА (безопасный режим, акки защищены)'}")
    killed = []
    if not enabled:
        killed = kill_running_rega(reason="rega.switch: выключение")
    return {"ok": True, "rega_enabled": enabled,
            "killed_pids": killed}


def kill_running_rega(reason=""):
    """🆘 v0.23: убить процессы рега-сервиса (РЕЖИМ rega, НЕ check) — по /proc.
    Рега стирает и перерегистрирует акки, поэтому при выключении тумблера её
    надо убить НЕМЕДЛЕННО, не дожидаясь собственной проверки свитча между
    попытками (та — вторая линия защиты). Возвращает список убитых pid."""
    killed = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cl = (d / "cmdline").read_bytes().decode(errors="replace").replace("\x00", " ")
        except Exception:
            continue
        if "services/rega/main.py" not in cl or " check" in cl:
            continue          # check-режим не трогаем — он ничего не регистрирует
        pid = int(d.name)
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
            log(f"🛡 Убит процесс регы pid {pid} ({reason})")
        except Exception:
            pass
    if killed:
        time.sleep(2)
        for pid in killed:
            try:
                os.kill(pid, signal.SIGKILL)   # добить, если не вышел
            except Exception:
                pass
    return killed


def harvest_window_active() -> bool:
    """🌾 Активно ли сейчас окно сбора (info/harvest_window.json не истекло)."""
    try:
        hw = json.loads((BASE / "info" / "harvest_window.json").read_text())
        return time.time() < float(hw.get("until_ts") or 0)
    except Exception:
        return False


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


def _stop_service(payload: dict) -> dict:
    name = payload.get("name", "")
    # фарм при остановке ещё и закрывает все роблоксы — даём ему время (15с зачистка)
    return PM.stop(name, timeout=25 if name == "farm" else 10)


# ---------- 🌾 СБОР УРОЖАЯ: окно для фарма (клиент пишет, фарм читает) ----------

def task_harvest_start(payload: dict) -> dict:
    minutes = max(1, min(int(payload.get("minutes") or 20), 180))
    data = {"until_ts": round(time.time() + minutes * 60, 1),
            "place_id": str(payload.get("place_id") or ""),
            "set_ts": round(time.time(), 1)}
    f = BASE / "info" / "harvest_window.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(f)                                   # атомарно
    log(f"🌾 Окно сбора: {minutes} мин (until {data['until_ts']})")
    return {"ok": True, **data}


def task_harvest_stop(payload: dict) -> dict:
    f = BASE / "info" / "harvest_window.json"
    try:
        f.unlink()
    except FileNotFoundError:
        pass
    log("🌾 Окно сбора снято")
    return {"ok": True, "note": "фарм вернётся к обычному циклу ≤30с"}


def task_rega_start(payload: dict) -> dict:
    """Полная авторегистрация (сервис rega, сам поднимет фарм по завершении).
    🛡 v0.20: при выключенном kill-switch — отказ (акки с лутом защищены)."""
    if not rega_switch_enabled():
        log("🛡 rega.start ОТКЛОНЁН: рега акков выключена (безопасный режим)")
        return {"ok": False,
                "note": "🛡 рега акков ОТКЛЮЧЕНА на этом телефоне (rega.switch) — "
                        "акки с лутом защищены; включи тумблером на дашборде"}
    r = PM.start("rega")
    if r.get("ok"):
        return {"ok": True, "note": "рега запущена (farm ⏹ уже сделан сервером)", **r}
    return r


def task_bypass_run(payload: dict) -> dict:
    """🔓 БАЙПАС КАК В v18.8: ставим флаг — фарм в ≤30с делает ПОЛНЫЙ цикл
    (Delta → реклама → ZEN-API → ключ → license) БЕЗ рестарта сервиса.
    Фарм не жил → запускаем: он стартует и сразу увидит флаг.
    🛡 v0.20: если на телефоне жив СБОРЩИК (collector) — фарм НЕ стартуем,
    байпас выполнит сборщик (тот же флаг info/bypass_force.json)."""
    data = {"ts": round(time.time(), 1),
            "source": str(payload.get("source") or "dashboard")}
    f = BASE / "info" / "bypass_force.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(f)                                   # атомарно
    was_running = PM.is_running("farm")
    collector_running = PM.is_running("collector")
    started = False
    if not was_running and not collector_running:
        r = PM.start("farm")
        started = bool(r.get("ok"))
    log(f"🔓 Флаг байпаса v18.8 поставлен (фарм "
        f"{'уже жил' if was_running else ('запущен' if started else 'НЕ запущен!')}"
        f"{'; СБОРЩИК жив — байпас выполнит он' if collector_running else ''})")
    return {"ok": True, "farm_was_running": was_running, "farm_started": started,
            "collector_running": collector_running,
            **data,
            "note": ("сборщик жив — полный байпас v18.8 выполнит СЕРВИС COLLECTOR ≤30с"
                     if collector_running else
                     "фарм выполнит полный байпас v18.8 ≤30с; "
                     "события bypass.ok/bypass.fail → 📅; вылетевшие клоны "
                     "перезапускаются в плейс мониторингом каждые 30с")}


def task_cookie_check(payload: dict) -> dict:
    """Быстрая проверка кук (rega check) — в фоне, результат придёт событиями.
    🛡 v0.20: во время активного окна сбора — отказ: check перезапускает клоны
    и срывает трейд."""
    if harvest_window_active():
        log("🛡 cookie.check отложен: идёт окно сбора (не мешаем трейду)")
        return {"ok": False,
                "note": "идёт окно сбора — проверка кук отложена, чтобы не "
                        "срывать трейд (запусти после окна)"}
    log("🍪 cookie.check: запускаю services/rega/main.py check")
    subprocess.Popen(
        [sys.executable, str(BASE / "services" / "rega" / "main.py"), "check"],
        cwd=str(BASE), env=ENV, start_new_session=True,
        stdout=open(BASE / "logs" / "services" / "rega_check.log", "ab"),
        stderr=subprocess.STDOUT)
    return {"ok": True, "note": "проверка запущена в фоне, события придут в 📅"}


def _task_service_start(payload: dict) -> dict:
    """🛡 v0.23: service.start rega подчиняется kill-switch (раньше обходил —
    сервер/панель могли запустить регу при выключенном тумблере)."""
    name = str(payload.get("name") or "")
    if name == "rega" and not rega_switch_enabled():
        log("🛡 service.start rega ОТКЛОНЁН: рега акков выключена (kill-switch)")
        return {"ok": False,
                "error": "🛡 рега акков выключена (kill-switch) — включи тумблером «Рега акков»"}
    return PM.start(name)


TASKS_SYNC = {
    "service.start":  _task_service_start,
    "service.stop":   _stop_service,
    "service.status": lambda p: PM.status(),
    "file.read":      task_file_read,
    "harvest.start":  task_harvest_start,
    "harvest.stop":   task_harvest_stop,
    "rega.start":     task_rega_start,
    "rega.switch":    task_rega_switch,
    "cookie.check":   task_cookie_check,
    "bypass.run":     task_bypass_run,
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

    elif task == "apk.update":
        # установка/обновление APK; перезагрузка телефона — ПОСЛЕ ответа серверу
        data = await asyncio.to_thread(run_apk_update, payload)
        await reply(data)
        if data.get("reboot_now"):
            log("📱 APK обновлены → перезагрузка телефона через 5с")
            await asyncio.sleep(5)
            await asyncio.to_thread(reboot_phone)
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
            "farm": get_farm_state(),      # last_key_time → дашборд: возраст ключа 🔑
        })
        await asyncio.sleep(interval)


async def events_loop(conn):
    """ЭТАП 2: доставка событий фарма (outbox). Отправка батча каждые 15с,
    offset двигается ТОЛЬКО после events_ack от сервера."""
    while True:
        await asyncio.sleep(15)
        try:
            batch = await asyncio.to_thread(OUTBOX.pending, 50)
            if not batch:
                continue
            await conn.send({"type": "events", "device_id": CONFIG["device_id"],
                             "events": batch})
        except Exception as e:
            log(f"📤 events: {e}")   # offset не двигаем — батч уйдёт повторно


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
        elif t == "events_ack":
            OUTBOX.commit(int(msg.get("accepted", 0)))
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
                asyncio.create_task(events_loop(conn)),
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
