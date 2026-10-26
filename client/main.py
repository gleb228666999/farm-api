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
- v0.24: 🌾 СБОР = HOLD (под сервер v0.8 «НОВЫЙ ЦИКЛ»): harvest.start с
        {"hold": true} пишет окно сбора БЕЗ СРОКА (until_ts = +30 дней) —
        фармеры/сборщики сидят в приватках с treid.lua/collet.lua, пока
        хозяин в панели не нажмёт «НОВЫЙ ЦИКЛ» (придёт harvest.stop → окно
        снято → фарм выйдет из сбора → сервер запустит регу → рега поднимет
        фарм). Раньше окно жило максимум 180 мин и фарм сам возвращался
        из сбора, ломая цикл хозяина.
- v0.25: 🚑 СПАСЕНИЕ СЛОМАВШЕГОСЯ ТЕЛЕФОНА (задача rescue.run, кнопка
        «🚑 Спас» в панели → POST /api/devices/{id}/rescue) — телефон крутит
        петлю «rega.attempt ok=false → rega.stray убивает клоны →
        farm.restart их оживает» часами и сам не останавливается. Цепочка
        по просьбе хозяина («кнопку остановки это хуйни -> взять куки
        если нет в пуле -> фарм»):
          1) рега-сервис УБИТ (kill_running_rega) — петля кончилась;
          2) застрявший флаг байпаса снят, фарм ⏹ (монитор перестаёт
             реанимировать клоны; фарм при стопе сам закрывает роблоксы),
             добиваем остатки com.roblox*;
          3) rega check: пустые/мёртвые сессии заменяются ИЗ ПУЛА СЕРВЕРА
             (БЕЗ регистрации новых акков — check только чинит);
          4) куки починились ПОЛНОСТЬЮ (или были живы) → farm ▶ + флаг
             байпаса (если ключу ≥24ч); починиться не вышло (пул пуст) →
             фарм ОСТАЁТСЯ ОСТАНОВЛЕННЫМ — иначе куки-гейт снова поднимет
             регу и петля вернётся.
        🔓 ПРАВИЛО ХОЗЯИНА: байпас ТОЛЬКО если ключу Дельты ≥24ч —
        bypass.run со свежим ключом (<24ч) отклоняется сразу (флаг даже
        не ставится, фарм не дёргается); force:true от владельца проходит
        мимо правила. Если ключа не было вовсе — байпас ДОЛЖЕН пройти.

        🌐 ПРОКСИ (v0.27): задача proxy.set — вся сеть телефона через SOCKS5.
        Поднимает локальный прозрачный форвардер (proxy_fwd.py,
        SO_ORIGINAL_DST → SOCKS5 с авторизацией) и через iptables (su)
        заворачивает в него ВЕСЬ исходящий TCP: Roblox/Delta/скрипты ходят
        через прокси, а WebSокет к серверу фермы и локальные сети — мимо
        (иначе потеряем телефон). UDP 443/80 режется — QUIC не утекает.
        Статус — в info/proxy.json → heartbeat → панель.
"""
import sys
import os
import json
import time
import signal
import hashlib
import asyncio
import socket
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

VERSION = "0.27"
HARVEST_HOLD_MINUTES = 30 * 24 * 60      # 🌾 v0.24: «бессрочное» окно сбора (30 дней) — снимается только harvest.stop
BYPASS_MIN_KEY_AGE_H = 24.0              # 🔓 v0.26: байпас только если ключу ≥24ч (правило хозяина)
RESCUE_CHECK_TIMEOUT = 20 * 60           # 🚑 v0.25: максимум ждём rega check (починка кук из пула)
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


def key_age_h() -> float | None:
    """🔓 v0.25: возраст ключа Дельты (часы) или None — ключа не было/неизвестно.
    Читается из info/farm_state.json (его пишет фарм после bypass.ok)."""
    st = get_farm_state() or {}
    try:
        kt = float(st.get("last_key_time") or 0)
    except Exception:
        return None
    if kt <= 0:
        return None
    return (time.time() - kt) / 3600


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
    """🌾 v0.24: HOLD-режим — окно сбора БЕЗ СРОКА. Сервер (v0.8) шлёт
    {"hold": true, "minutes": 0}: фармеры/сборщики заходят в приватки
    с treid.lua/collet.lua и сидят там, пока хозяин не нажмёт «НОВЫЙ ЦИКЛ»
    (придёт harvest.stop и файл окна удалится) — раньше окно было максимум
    на 180 мин и фарм сам возвращался из сбора, ломая цикл хозяина.
    Обычный режим с минутами тоже оставлен (совместимость)."""
    hold = bool(payload.get("hold")) or not str(payload.get("minutes") or "").strip() \
        or int(payload.get("minutes") or 0) <= 0
    if hold:
        minutes = HARVEST_HOLD_MINUTES          # 30 дней — «бессрочно» до НОВОГО ЦИКЛА
    else:
        minutes = max(1, min(int(payload.get("minutes") or 20), 180))
    data = {"until_ts": round(time.time() + minutes * 60, 1),
            "place_id": str(payload.get("place_id") or ""),
            "set_ts": round(time.time(), 1),
            "hold": hold}
    f = BASE / "info" / "harvest_window.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(f)                                   # атомарно
    log(f"🌾 Окно сбора: {'БЕССРОЧНО (HOLD — до кнопки «НОВЫЙ ЦИКЛ»)' if hold else f'{minutes} мин'} "
        f"(until {data['until_ts']})")
    return {"ok": True, **data}


def task_harvest_stop(payload: dict) -> dict:
    f = BASE / "info" / "harvest_window.json"
    try:
        f.unlink()
    except FileNotFoundError:
        pass
    log("🌾 Окно сбора снято (HOLD завершён — ждём «НОВЫЙ ЦИКЛ»/регу)")
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
    байпас выполнит сборщик (тот же флаг info/bypass_force.json).
    🔓 v0.26 ПРАВИЛО ХОЗЯИНА: байпас ТОЛЬКО если ключу ≥24ч — свежий ключ
    (<24ч) = байпас отклонён СРАЗУ (флаг даже не ставится, фарм не дёргается).
    force:true (владелец нажал FORCE в панели) проходит мимо правила.
    Ключа не было вовсе (last_key_time пуст) — байпас ДОЛЖЕН пройти."""
    force = bool(payload.get("force"))
    age = key_age_h()
    if not force and age is not None and age < BYPASS_MIN_KEY_AGE_H:
        log(f"🔓 Байпас ОТКЛОНЁН: ключу {age:.1f}ч < {BYPASS_MIN_KEY_AGE_H:.0f}ч — "
            f"байпас не нужен (правило хозяина). FORCE можно передать из панели")
        return {"ok": False, "key_age_h": round(age, 1),
                "min_key_age_h": BYPASS_MIN_KEY_AGE_H,
                "note": f"ключ свежий ({age:.1f}ч < {BYPASS_MIN_KEY_AGE_H:.0f}ч) — "
                        f"байпас не нужен и НЕ запущен; флаг на телефон не ставился"}
    data = {"ts": round(time.time(), 1),
            "source": str(payload.get("source") or "dashboard"),
            "force": force}
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
    age_note = (f"ключу {age:.1f}ч — правило ≥24ч пройдено"
                if age is not None else "ключа не было — байпас обязателен")
    log(f"🔓 Флаг байпаса v18.8 поставлен ({age_note}"
        f"{'; FORCE владельца' if force else ''}; фарм "
        f"{'уже жил' if was_running else ('запущен' if started else 'НЕ запущен!')}"
        f"{'; СБОРЩИК жив — байпас выполнит он' if collector_running else ''})")
    return {"ok": True, "farm_was_running": was_running, "farm_started": started,
            "collector_running": collector_running,
            "key_age_h": (round(age, 1) if age is not None else None),
            "forced": force,
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


# ---------- 🚑 СПАСЕНИЕ сломавшегося телефона (v0.25) ----------

def _read_last_check_done(since_ts: float) -> dict | None:
    """Последнее событие check.done из info/rega_events.jsonl после since_ts.
    rega check пишет {replaced: N, need: M} — по нему решаем судьбу фарма."""
    f = BASE / "info" / "rega_events.jsonl"
    try:
        for line in reversed(f.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") != "check.done":
                continue
            if float(ev.get("ts") or 0) < since_ts - 5:
                return None                    # свежего check.done нет
            return ev.get("info") or {}
    except Exception:
        pass
    return None


def task_rescue_run(payload: dict) -> dict:
    """🚑 v0.25 АВАРИЙНАЯ КНОПКА: телефон зациклился —
    «rega.attempt ok=false → rega.stray убивает клоны → farm.restart оживает»
    по кругу часами (жалоба хозяина 25.10, phone_dd5423). Цепочка хозяина:
      СТОП ПЕТЛИ → ВЗЯТЬ КУКИ ЕСЛИ НЕТ (из пула!) → ФАРМ.
    Шаги:
      1) рега-сервис УБИТ (kill_running_rega — режим rega, check не трогаем);
      2) застрявший флаг байпаса снят (петле нечего подкидывать);
      3) фарм ⏹ — его монитор перестаёт реанимировать клоны (кто с кем
         бьётся); фарм при стопе сам закрывает ВСЕ роблоксы; добиваем
         остатки com.roblox* через su (best effort);
      4) rega check (ТОЛЬКО починка, регистрации НЕТ): пустые/мёртвые
         сессии заменяются куками ИЗ ПУЛА СЕРВЕРА;
      5) куки починились ПОЛНОСТЬЮ (или были живы) → farm ▶ и флаг байпаса
         (если ключу ≥24ч — правило хозяина); НЕ починились (пул пуст) →
         фарм ОСТАЁТСЯ ОСТАНОВЛЕННЫМ: куки-гейт фармa в противном случае
         снова поднял бы регу — петля вернулась бы."""
    src = str(payload.get("source") or "panel")
    log(f"🚑 СПАСЕНИЕ ({src}): останавливаю петлю рега↔фарм...")
    # 1) убить идущую регу
    killed = kill_running_rega(reason="rescue: аварийная кнопка")
    # 2) снять застрявший флаг байпаса
    try:
        (BASE / "info" / "bypass_force.json").unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"🚑 флаг байпаса не удался: {e}")
    # 3) фарм ⏹ (+ зачистка роблоксов)
    farm_stop = PM.stop("farm", timeout=25)
    log(f"🚑 фарм ⏹: {farm_stop}")
    sh('su -c "pkill -f com.roblox"')     # добить случайные клоны (best effort)
    time.sleep(2)
    # 4) куки из пула: rega check (это НЕ регистрация — только замена кук)
    check_script = BASE / "services" / "rega" / "main.py"
    if not check_script.is_file():
        return {"ok": False, "killed_rega_pids": killed, "farm_stop": farm_stop,
                "error": "нет services/rega/main.py — update клиента не докатился"}
    start_ts = time.time()
    log("🚑 запускаю rega check: куки из пула сервера (без регистрации)...")
    try:
        (BASE / "logs" / "services").mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, str(check_script), "check"],
            cwd=str(BASE), env=ENV, start_new_session=True,
            stdout=open(BASE / "logs" / "services" / "rega_check.log", "ab"),
            stderr=subprocess.STDOUT)
    except Exception as e:
        return {"ok": False, "killed_rega_pids": killed, "farm_stop": farm_stop,
                "error": f"check не запустился: {e}"}
    waited = 0
    while proc.poll() is None and waited < RESCUE_CHECK_TIMEOUT:
        time.sleep(5)
        waited += 5
    check_timed_out = proc.poll() is None
    if check_timed_out:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
        log(f"🚑 check не уложился в {RESCUE_CHECK_TIMEOUT // 60} мин — убит")
    info = _read_last_check_done(start_ts) or {}
    need = info.get("need")
    replaced = info.get("replaced")
    log(f"🚑 check завершён ({waited}с, timeout={check_timed_out}): "
        f"need={need}, replaced={replaced}")
    # 5) решение по фарму: старт ТОЛЬКО при полной починке (иначе петля вернётся)
    farm_started, bypass_queued = False, False
    if need is None:
        verdict = ("результат check не прочитан — фарм ОСТАВЛЕН ОСТАНОВЛЕННЫМ "
                   "(осторожный режим: петля не должна вернуться); "
                   "глянь logs/services/rega_check.log и farm.log")
    elif int(need or 0) == 0:
        r = PM.start("farm")
        farm_started = bool(r.get("ok"))
        verdict = "куки живы — фарм запущен"
    elif replaced and int(replaced) >= int(need):
        r = PM.start("farm")
        farm_started = bool(r.get("ok"))
        verdict = f"куки заменены из пула ({replaced}/{need}) — фарм запущен"
    else:
        verdict = (f"починить не вышло (заменено {replaced or 0} из {need}) — "
                   f"фарм ОСТАВЛЕН ОСТАНОВЛЕННЫМ, чтобы куки-гейт не поднял "
                   f"регу снова. Долей куки в пул и нажми 🚑 ещё раз")
    # флаг байпаса — по правилу хозяина (ключу ≥24ч; нет ключа = нужен)
    if farm_started:
        age = key_age_h()
        if age is None or age >= BYPASS_MIN_KEY_AGE_H:
            f = BASE / "info" / "bypass_force.json"
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ts": round(time.time(), 1),
                                       "source": "rescue", "force": False}))
            tmp.replace(f)
            bypass_queued = True
            log(f"🚑 флаг байпаса поставлен "
                f"({'ключа не было' if age is None else f'ключу {age:.1f}ч'})")
        else:
            log(f"🚑 байпас не ставлю: ключу {age:.1f}ч < {BYPASS_MIN_KEY_AGE_H:.0f}ч")
    result = {"ok": True, "source": src, "killed_rega_pids": killed,
              "farm_stop": farm_stop, "check_need": need,
              "check_replaced": replaced, "check_timed_out": check_timed_out,
              "farm_started": farm_started, "bypass_queued": bypass_queued,
              "verdict": verdict,
              "note": f"🚑 {verdict}"}
    log(f"🚑 СПАСЕНИЕ ГОТОВО: {verdict}")
    return result


def _task_service_start(payload: dict) -> dict:
    """🛡 v0.23: service.start rega подчиняется kill-switch (раньше обходил —
    сервер/панель могли запустить регу при выключенном тумблере)."""
    name = str(payload.get("name") or "")
    if name == "rega" and not rega_switch_enabled():
        log("🛡 service.start rega ОТКЛОНЁН: рега акков выключена (kill-switch)")
        return {"ok": False,
                "error": "🛡 рега акков выключена (kill-switch) — включи тумблером «Рега акков»"}
    return PM.start(name)


# ---------- 🌐 ПРОКСИ (v0.27): вся сеть телефона через SOCKS5 ----------

PROXY_STATE_FILE = BASE / "info" / "proxy.json"
PROXY_FWD_PORT = 8888
PROXY_FWD_PIDFILE = BASE / "info" / "proxy_fwd.pid"
PROXY_FWD_LOG = BASE / "logs" / "proxy_fwd.log"
PROXY_CHAIN = "FARM_PROXY"      # имя iptables-цепочки
PROXY_COMMENT = "farmproxy"     # комментарий правил в OUTPUT


def get_proxy_state() -> dict:
    """Статус прокси для heartbeat/панели (БЕЗ пароля)."""
    try:
        st = json.loads(PROXY_STATE_FILE.read_text())
        return {"enabled": bool(st.get("enabled")),
                "proxy_id": st.get("proxy_id"),
                "host": st.get("host"), "port": st.get("port"),
                "applied": bool(st.get("applied")),
                "applied_ts": st.get("applied_ts"),
                "error": (st.get("error") or "")[:120]}
    except Exception:
        return {"enabled": False, "proxy_id": None, "applied": False}


def _proxy_su(cmd: str) -> tuple[bool, str]:
    """Привилегированная команда (iptables/settings) через su. (ok, вывод)."""
    try:
        r = subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=25)
        return (r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()[-400:])
    except Exception as e:
        return False, str(e)[:200]


def _proxy_state_write(st: dict):
    try:
        (BASE / "info").mkdir(parents=True, exist_ok=True)
        tmp = PROXY_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(PROXY_STATE_FILE)               # атомарно
    except Exception as e:
        log(f"🌐 не смог записать proxy.json: {e}")


def _proxy_stop() -> dict:
    """Выключить всё прокси: убить форвардер, снять правила iptables,
    сбросить системный http_proxy. Безопасно вызывать всегда."""
    r = {"fwd_killed": False, "iptables_cleared": False}
    try:
        pid = int(PROXY_FWD_PIDFILE.read_text().strip())
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        r["fwd_killed"] = True
    except Exception:
        try:
            subprocess.run(["pkill", "-f", "proxy_fwd.py"], capture_output=True, timeout=5)
            r["fwd_killed"] = True
        except Exception:
            pass
    ok = True
    for cmd in (
        f"iptables -t nat -D OUTPUT -p tcp -m comment --comment {PROXY_COMMENT} -j {PROXY_CHAIN}",
        f"iptables -t nat -F {PROXY_CHAIN}; iptables -t nat -X {PROXY_CHAIN}",
        f"iptables -D OUTPUT -p udp -m multiport --dports 443,80 "
        f"-m comment --comment {PROXY_COMMENT} -j REJECT",
        "settings put global http_proxy :0",
    ):
        okc, _ = _proxy_su(f"{cmd} 2>/dev/null; true")
        ok = ok and okc
    r["iptables_cleared"] = ok
    return r


def _proxy_ip_exclusions(host: str) -> list:
    """Кому ходить НАПРЯМУЮ (не заворачивать в прокси): сам прокси, сервер
    фермы, локальные/служебные сети. Иначе теряем связь с телефоном."""
    ips = set()
    for h in (host, urllib.parse.urlparse(CONFIG.get("server_url") or "").hostname):
        if not h:
            continue
        try:
            ips.add(socket.gethostbyname(h))
        except Exception:
            pass
    if host.count(".") == 3:
        ips.add(host)                              # на случай DNS-фиаско
    return sorted(ips)


def _proxy_iptables_cmds(excl_ips: list) -> list:
    cmds = [f"iptables -t nat -N {PROXY_CHAIN} 2>/dev/null; iptables -t nat -F {PROXY_CHAIN}"]
    for ip in excl_ips:
        cmds.append(f"iptables -t nat -A {PROXY_CHAIN} -d {ip} -j RETURN")
    for net in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                "169.254.0.0/16", "224.0.0.0/4", "255.255.255.255"):
        cmds.append(f"iptables -t nat -A {PROXY_CHAIN} -d {net} -j RETURN")
    cmds.append(f"iptables -t nat -A {PROXY_CHAIN} -p tcp -j REDIRECT --to-ports {PROXY_FWD_PORT}")
    cmds.append(f"iptables -t nat -C OUTPUT -p tcp -m comment --comment {PROXY_COMMENT} "
                f"-j {PROXY_CHAIN} || iptables -t nat -A OUTPUT -p tcp "
                f"-m comment --comment {PROXY_COMMENT} -j {PROXY_CHAIN}")
    # UDP 443/80 режем: QUIC не должен утекать мимо прокси — приложения
    # сами откатятся на TCP (HTTP/2), который уже идёт через форвардер
    cmds.append(f"iptables -C OUTPUT -p udp -m multiport --dports 443,80 "
                f"-m comment --comment {PROXY_COMMENT} -j REJECT || "
                f"iptables -A OUTPUT -p udp -m multiport --dports 443,80 "
                f"-m comment --comment {PROXY_COMMENT} -j REJECT")
    return cmds


def task_proxy_set(payload: dict) -> dict:
    """🌐 v0.27 ВКЛ/ВЫКЛ прокси (вся сеть через SOCKS5).
    payload: {"proxy": "socks5://login:pass@ip:port"|null, "proxy_id": N}
    1) глушим старое (форвардер + правила)  2) поднимаем proxy_fwd.py
    3) iptables: весь OUTPUT TCP → 8888 (исключения: прокси, сервер, лок)
    4) проверяем правило → честный вердикт → статус в info/proxy.json."""
    url = payload.get("proxy")
    proxy_id = payload.get("proxy_id")
    src = str(payload.get("source") or "panel")
    st = {"enabled": False, "applied": False, "proxy_id": proxy_id,
          "host": None, "port": None, "applied_ts": None, "error": None}

    log(f"🌐 proxy.set ({src}): {'включаю ' + url if url else 'выключаю прокси'}")
    stop = _proxy_stop()
    if not url:
        _proxy_state_write({**st, "ts": time.time()})
        return {"ok": True, "enabled": False,
                "note": f"прокси снят (форвардер остановлен: {stop.get('fwd_killed')}; "
                        f"правила сняты: {stop.get('iptables_cleared')})"}

    u = urllib.parse.urlparse(str(url))
    scheme = (u.scheme or "").lower()
    if scheme not in ("socks5", "socks5h"):
        st["error"] = f"схема {scheme}:// не поддерживается — нужен socks5 (у продавца выбирай SOCKS5)"
        _proxy_state_write({**st, "ts": time.time()})
        log(f"❌ {st['error']}")
        return {"ok": False, "error": st["error"]}
    host, port = u.hostname, u.port or 1080
    if not host:
        st["error"] = "в URL нет адреса прокси"
        _proxy_state_write({**st, "ts": time.time()})
        return {"ok": False, "error": st["error"]}
    st.update({"host": host, "port": port})

    # 1) поднимаем форвардер
    try:
        (BASE / "logs").mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [sys.executable, str(BASE / "proxy_fwd.py"),
             "--listen", f"127.0.0.1:{PROXY_FWD_PORT}",
             "--upstream", str(url),
             "--log", str(PROXY_FWD_LOG), "--pidfile", str(PROXY_FWD_PIDFILE)],
            env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except Exception as e:
        st["error"] = f"форвардер не запустился: {e}"
        _proxy_state_write({**st, "ts": time.time()})
        return {"ok": False, "error": st["error"]}

    alive = False
    for _ in range(24):                       # ждём ≤6с пока порт откроется
        try:
            with socket.create_connection(("127.0.0.1", PROXY_FWD_PORT), timeout=0.5):
                alive = True
                break
        except OSError:
            time.sleep(0.25)
    if not alive:
        st["error"] = ("форвардер не поднял порт (см. logs/proxy_fwd.log; "
                       "возможно неверный логин/пароль или адрес)")
        _proxy_state_write({**st, "ts": time.time()})
        return {"ok": False, "error": st["error"]}

    # 2) iptables: весь OUTPUT TCP → локальный порт
    excl = _proxy_ip_exclusions(host)
    log(f"🌐 исключения (напрямую): {', '.join(excl) or '—'} + локальные сети")
    fails = []
    for cmd in _proxy_iptables_cmds(excl):
        okc, out = _proxy_su(cmd)
        if not okc:
            fails.append(f"{cmd[:64]}… → {out[-120:]}")
    if fails:
        st["error"] = "iptables не применился (нет root/iptables?) — прокси НЕ включён: " + " | ".join(fails[:2])
        _proxy_state_write({**st, "ts": time.time()})
        log(f"❌ {st['error']}")
        return {"ok": False, "error": st["error"]}

    # 3) верификация: правило реально в OUTPUT?
    okv, vout = _proxy_su(f"iptables -t nat -L OUTPUT -n --line-numbers | grep {PROXY_CHAIN}")
    if not okv or PROXY_CHAIN not in vout:
        st["error"] = f"правило не подтвердилось: {vout[:160]}"
        _proxy_state_write({**st, "ts": time.time()})
        return {"ok": False, "error": st["error"]}

    st.update({"enabled": True, "applied": True, "applied_ts": time.time()})
    _proxy_state_write({**st, "ts": time.time()})
    log(f"✅ ПРОКСИ ВКЛЮЧЁН: вся сеть TCP → 127.0.0.1:{PROXY_FWD_PORT} → {host}:{port}")
    return {"ok": True, "enabled": True, "applied": True,
            "host": host, "port": port, "excluded": excl,
            "note": "вся сеть телефона идёт через прокси (сервер фермы — напрямую)"}


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
    "rescue.run":     task_rescue_run,       # 🚑 v0.25: спасение сломавшегося телефона
    "proxy.set":      task_proxy_set,        # 🌐 v0.27: вся сеть через SOCKS5
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
            "proxy": get_proxy_state(),    # 🌐 v0.27: статус прокси → панель
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
                "info": {**get_device_info(), "proxy": get_proxy_state()},
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
