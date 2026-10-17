#!/usr/bin/env python3
"""
🆕 REGA SERVICE (services/rega/main.py) — авторегистрация + куки + пул НА СЕРВЕРЕ

Принципы из farm.py v18.8 (хозяина), адаптированы под систему фермы:
- Пул кук НЕ на GitHub, а НА СЕРВЕРЕ (farm.db → /api/pool/*) — бронь с TTL,
  одну куку два телефона не получат.
- Излишки реги (>5) → пул на сервере. Недобор → добор из пула → крайний
  резерв: архив сервера → локальный архив.
- Отработанные куки → архив сервера (можно поднять позже), мёртвые → удаляются.
- Режим check: проверка кук на всех пакетах; вылетела кука → замена из пула,
  если пул пуст → из архива (вход по новой куке без полной регы).
- Одиночный экземпляр (flock info/rega.lock): фарм и сервер не могут запустить
  регу дважды; check при активной реге тоже пропускается.
- Только stdlib (urllib вместо requests) — на телефоне pip НЕ нужен.

Режимы: python services/rega/main.py [rega|check]
- rega  — полная авторегистрация (запускает сервер: farm ⏹ → rega.start)
- check — быстрая проверка и починка кук (запускается по cookie.check)

События: info/rega_events.jsonl (клиент возит на сервер через outbox).
После реги сервис ставит farm=running в services_state.json → watchdog
клиента сам поднимет фарм. Регу может прервать SIGTERM (farm ⏹-стиль).

v18.8 (принципы хозяина, без изменений):
- 40 попыток = 4 раунда × 10 попыток, после раунда пауза 15 мин (rate-limit тоже 15)
- 1 телефон = 5 акков (ферма), излишки в пул
- кука №1 → com.roblox.client (Delta) — байпасу нужна залогиненная Дельта
- инъекция .ROBLOSECURITY в WebView SQLite + prefs.xml (nick/userid)
- регистрация по UI-координатам (портрет)
"""
import os
import sys
import json
import time
import re
import html
import shutil
import signal
import sqlite3
import random
import string
import hashlib
import fcntl
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ==========================================
# ⚙️ БАЗА / СЕРВЕР / ФАЙЛЫ
# ==========================================

BASE = Path(__file__).resolve().parents[2]        # services/rega/main.py -> ~/farm
try:
    CONFIG = json.loads((BASE / "config.json").read_text())
except Exception:
    CONFIG = {}
SERVER = (CONFIG.get("server_url") or "").rstrip("/")
DEVICE_ID = str(CONFIG.get("device_id") or "?")

PACKAGE_MAIN = "com.roblox.client"
PLACE_ID = "142823291"                             # фарм-плейс (куда возвращать клоны)

OUT_DIR = "/storage/emulated/0/RobloxFarm"
COOKIES_F = os.path.join(OUT_DIR, "cookies.txt")
ACCOUNTS_F = os.path.join(OUT_DIR, "accounts.txt")
ARCHIVE_DIR = os.path.join(OUT_DIR, "archive")
POOL_LOCAL_F = os.path.join(OUT_DIR, "cookie_pool.json")

TERMUX_HOME = os.environ.get("HOME", "/data/data/com.termux/files/home")
WORK_DB = os.path.join(TERMUX_HOME, "Cookies_work.db")

EVENTS_FILE = BASE / "info" / "rega_events.jsonl"
EVENTS_MAX_BYTES = 512 * 1024
EVENTS_KEEP = 300
STATE_FILE = BASE / "info" / "rega_state.json"

# --- рега: принципы v18.8 ---
DEFAULT_TARGET = 5          # 1 телефон = 5 акков
REG_ATTEMPTS = 10           # попыток в раунде
MAX_ROUNDS = 4              # 4×10 = 40 попыток
RATE_LIMIT_PAUSE = 15 * 60  # rate-limit → пауза 15 мин
ROUND_PAUSE_MIN = 15        # между раундами 15 мин
FARMERS_LIMIT = 4           # клоны фермы (5-й = main)
REG_MAIN_FIRST = True       # кука №1 → Delta (байпас)
ARCHIVE_SCAN_LIMIT = 80

# ==========================================
# 🛑 СТОП (SIGTERM от ProcessManager)
# ==========================================

_STOP = [False]


def _sigterm(signum, frame):
    log("🛑 SIGTERM: останавливаю регу (мягко)...")
    _STOP[0] = True


def stop_requested() -> bool:
    return _STOP[0]


def interruptible_sleep(total_sec, step=5) -> bool:
    """True = стоп запрошен во время сна."""
    end = time.time() + total_sec
    while time.time() < end:
        if stop_requested():
            return True
        time.sleep(min(step, max(0.2, end - time.time())))
    return stop_requested()


state = {"last_reg_date": "", "last_reg_time": 0.0}


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def load_state():
    try:
        state.update(json.loads(STATE_FILE.read_text()))
    except Exception:
        pass


def save_state():
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log(f"⚠️ save_state: {e}")


def emit(etype, **info):
    """Событие регы → info/rega_events.jsonl (одна JSON-строка)."""
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if EVENTS_FILE.exists() and EVENTS_FILE.stat().st_size > EVENTS_MAX_BYTES:
                tail = EVENTS_FILE.read_text().splitlines()[-EVENTS_KEEP:]
                tmp = EVENTS_FILE.with_suffix(".tmp")
                tmp.write_text("\n".join(tail) + "\n")
                tmp.replace(EVENTS_FILE)
        except Exception:
            pass
        ev = {"id": f"{int(time.time()*1000):x}-{os.urandom(3).hex()}",
              "ts": round(time.time(), 2), "type": etype, "info": info}
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"⚠️ emit({etype}): {e}")


# ==========================================
# 🛠 su + базовые действия
# ==========================================

def find_su() -> str:
    for cand in ("su", "/system/bin/su", "/system/xbin/su", "/sbin/su"):
        found = shutil.which(cand)
        if found:
            return found
        if cand.startswith("/") and os.path.exists(cand):
            return cand
    return "su"


SU_BIN = find_su()


def run_su(cmd, timeout=15):
    try:
        r = subprocess.run([SU_BIN, "-c", cmd], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as e:
        return False, "", str(e)


def tap(x, y, delay=0):
    run_su(f"input tap {x} {y}", timeout=5)
    if delay:
        time.sleep(delay)


def type_text(text, timeout=25):
    safe = text.replace("'", "'\\''").replace(" ", "%s")
    ok, _, err = run_su(f"input text '{safe}'", timeout=timeout)
    if not ok:
        log(f"   ⚠️ input text error: {err}")
    return ok


def select_all_delete():
    run_su("input keycombination 113 29", timeout=5)
    time.sleep(0.3)
    run_su("input keyevent 67", timeout=5)
    time.sleep(0.3)


def set_portrait():
    run_su("settings put system user_rotation 0", timeout=5)
    run_su("settings put system accelerometer_rotation 1", timeout=5)


def wake_screen():
    ok, out, _ = run_su("dumpsys power | grep 'mWakefulness='", timeout=5)
    if ok and "mWakefulness=Awake" in out:
        return
    log("🌅 Экран выключен — буджу")
    run_su("input keyevent 224", timeout=5)
    time.sleep(1)
    run_su("input keyevent 82", timeout=5)
    time.sleep(1)


def wake_lock():
    try:
        subprocess.run(["termux-wake-lock"], capture_output=True, timeout=5)
    except Exception:
        pass


# ==========================================
# 📄 UI DUMP
# ==========================================

_UI_CACHE = {"ts": 0.0, "xml": ""}


def ui_cache_clear():
    _UI_CACHE["xml"] = ""
    _UI_CACHE["ts"] = 0.0


def ui_dump():
    if time.time() - _UI_CACHE["ts"] < 1.0:
        return _UI_CACHE["xml"]
    ok, out, _ = run_su(
        "rm -f /data/local/tmp/ui.xml; "
        "uiautomator dump /data/local/tmp/ui.xml >/dev/null 2>&1; "
        "cat /data/local/tmp/ui.xml 2>/dev/null", timeout=25)
    xml = out if (ok and out) else ""
    _UI_CACHE["ts"] = time.time()
    _UI_CACHE["xml"] = xml
    return xml


# ==========================================
# 📱 ПАКЕТЫ
# ==========================================

def roblox_pkgs():
    ok, out, _ = run_su("pm list packages com.roblox", timeout=10)
    if not ok:
        return []
    return sorted(l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("package:"))


def get_farm_packages():
    return [pkg for pkg in roblox_pkgs() if pkg != PACKAGE_MAIN][:FARMERS_LIMIT]


def deep_link_start(pkg, place_id=None, timeout=10):
    place = place_id or PLACE_ID
    return run_su(
        f"am start -a android.intent.action.VIEW "
        f"-d 'roblox://experiences/start?placeId={place}' {pkg}",
        timeout=timeout)


def kill_main_only():
    run_su(f"am force-stop {PACKAGE_MAIN}", timeout=5)
    run_su("am force-stop com.android.chrome", timeout=5)
    time.sleep(2)


def kill_all_roblox():
    log("🛑 Убиваю ВСЕ процессы Roblox/Chrome...")
    ok, out, _ = run_su("pm list packages com.roblox", timeout=10)
    if ok:
        for line in out.splitlines():
            if line.startswith("package:"):
                run_su(f"am force-stop {line.split(':', 1)[1]}", timeout=5)
    run_su("am force-stop com.android.chrome", timeout=5)
    run_su("am force-stop com.android.browser", timeout=5)
    time.sleep(5)


def launch():
    """🚀 Запуск MAIN для регистрации"""
    log(f"🚀 Запуск {PACKAGE_MAIN} для реги, жду 20с")
    run_su(f"monkey -p {PACKAGE_MAIN} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1", timeout=10)
    time.sleep(20)


# ==========================================
# 🍪 КУКИ — чтение / инъекция (v18.8)
# ==========================================

def _cookie_hash(c):
    return hashlib.sha1(c.encode()).hexdigest()[:12]


def pkg_uid(pkg):
    ok, out, _ = run_su(f"stat -c %u /data/data/{pkg}")
    return out.strip() if ok and out.strip() else None


def fix_ownership(pkg, path):
    uid = pkg_uid(pkg)
    if uid:
        run_su(f"chown -R {uid}:{uid} '{path}'")
    run_su(f"chmod -R u+rwX '{path}'")


def copy_db_to_work(db):
    run_su(f"rm -f '{WORK_DB}' '{WORK_DB}-wal' '{WORK_DB}-journal' '{WORK_DB}-shm'")
    run_su(f"cp '{db}' '{WORK_DB}' 2>/dev/null")
    run_su(f"cp '{db}-wal' '{WORK_DB}-wal' 2>/dev/null")
    run_su(f"cp '{db}-shm' '{WORK_DB}-shm' 2>/dev/null")
    run_su(f"cp '{db}-journal' '{WORK_DB}-journal' 2>/dev/null")
    run_su(f"chmod 666 '{WORK_DB}' '{WORK_DB}-wal' '{WORK_DB}-shm' '{WORK_DB}-journal' 2>/dev/null")


def clean_work_db():
    run_su(f"rm -f '{WORK_DB}' '{WORK_DB}-wal' '{WORK_DB}-journal' '{WORK_DB}-shm'")


def get_table_cols():
    try:
        con = sqlite3.connect(WORK_DB)
        has = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cookies'").fetchone()
        if not has:
            con.close()
            return []
        cols = [r[1] for r in con.execute("PRAGMA table_info(cookies)").fetchall()]
        con.close()
        return cols
    except Exception:
        return []


def cookie_db_candidates(pkg):
    base = f"/data/data/{pkg}/app_webview"
    return [f"{base}/Default/Cookies",
            f"{base}/Default/Network/Cookies",
            f"{base}/Cookies"]


def _read_roblosecurity(db):
    if not run_su(f"test -f '{db}'")[0]:
        return None
    copy_db_to_work(db)
    con = None
    try:
        con = sqlite3.connect(WORK_DB)
        has = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name='cookies'").fetchone()
        if not has:
            return None
        rows = con.execute("SELECT value FROM cookies WHERE name='.ROBLOSECURITY' "
                           "AND host_key LIKE '%roblox.com' ORDER BY expires_utc DESC").fetchall()
        for (val,) in rows:
            if val and len(val) > 40:
                return val.strip()
    except Exception:
        pass
    finally:
        if con:
            try:
                con.close()
            except Exception:
                pass
        clean_work_db()
    return None


def extract_cookie(pkg=PACKAGE_MAIN, wait=30):
    deadline = time.time() + wait
    while time.time() < deadline:
        if stop_requested():
            return None
        for db in cookie_db_candidates(pkg):
            v = _read_roblosecurity(db)
            if v:
                return v
        time.sleep(3)
    return None


def has_session(pkg):
    for db in cookie_db_candidates(pkg):
        if not run_su(f"test -f '{db}'")[0]:
            continue
        copy_db_to_work(db)
        if not get_table_cols():
            clean_work_db()
            continue
        con = None
        try:
            con = sqlite3.connect(WORK_DB)
            rows = con.execute("SELECT length(value) FROM cookies WHERE name='.ROBLOSECURITY'").fetchall()
            if any(r[0] and r[0] > 40 for r in rows):
                return True
        except Exception:
            pass
        finally:
            if con:
                try:
                    con.close()
                except Exception:
                    pass
            clean_work_db()
    return False


def fetch_user_info_full(cookie):
    """API Roblox: жива ли кука (stdlib urllib)."""
    try:
        req = urllib.request.Request(
            "https://users.roblox.com/v1/users/authenticated",
            headers={"Cookie": f".ROBLOSECURITY={cookie}", "User-Agent": "Roblox/Win32"})
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200:
                d = json.loads(r.read().decode())
                return "ok", d.get("id"), d.get("name")
            return "error", None, None
    except urllib.error.HTTPError as e:
        return ("dead", None, None) if e.code == 401 else ("error", None, None)
    except Exception:
        return "error", None, None


def webview_version():
    for wv in ("com.google.android.webview", "com.android.webview",
               "com.google.android.trichromelibrary"):
        ok, out, _ = run_su(f"dumpsys package {wv} | grep -m1 versionName")
        if ok and out:
            m = re.search(r'versionName=(\d+)', out)
            if m:
                return int(m.group(1))
    return None


def _win_to_chrome_time(days=365):
    return int((time.time() + days * 86400) * 1_000_000) + 11644473600 * 1_000_000


SCHEMA_V94 = """CREATE TABLE cookies(
    creation_utc INTEGER NOT NULL, top_frame_site_key TEXT NOT NULL,
    host_key TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,
    encrypted_value BLOB DEFAULT '', path TEXT NOT NULL, expires_utc INTEGER NOT NULL,
    is_secure INTEGER NOT NULL, is_httponly INTEGER NOT NULL, last_access_utc INTEGER NOT NULL,
    has_expires INTEGER NOT NULL DEFAULT 1, is_persistent INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 1, samesite INTEGER NOT NULL DEFAULT -1,
    source_scheme INTEGER NOT NULL DEFAULT 0, source_port INTEGER NOT NULL DEFAULT -1,
    is_same_party INTEGER NOT NULL DEFAULT 0)"""

SCHEMA_V150 = """CREATE TABLE cookies(
    creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, top_frame_site_key TEXT NOT NULL,
    name TEXT NOT NULL, value TEXT NOT NULL, encrypted_value BLOB NOT NULL,
    path TEXT NOT NULL, expires_utc INTEGER NOT NULL, is_secure INTEGER NOT NULL,
    is_httponly INTEGER NOT NULL, last_access_utc INTEGER NOT NULL, has_expires INTEGER NOT NULL,
    is_persistent INTEGER NOT NULL, priority INTEGER NOT NULL, samesite INTEGER NOT NULL,
    source_scheme INTEGER NOT NULL, source_port INTEGER NOT NULL, last_update_utc INTEGER NOT NULL,
    source_type INTEGER NOT NULL, has_cross_site_ancestor INTEGER NOT NULL)"""


def _native_create_one(pkg, db):
    for _attempt in range(2):
        run_su(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1", timeout=10)
        time.sleep(8)
        run_su(f"am force-stop {pkg}", timeout=5)
        time.sleep(1)
        if run_su(f"test -f '{db}'")[0]:
            return True
    return False


def _native_create_any(pkg):
    for _attempt in range(2):
        run_su(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1", timeout=10)
        time.sleep(8)
        run_su(f"am force-stop {pkg}", timeout=5)
        time.sleep(1)
        for db in cookie_db_candidates(pkg):
            if run_su(f"test -f '{db}'")[0]:
                return db
    return None


def _inject_cookie_into_db(pkg, db, cookie, wv):
    need_recreate = False
    if not run_su(f"test -f '{db}'")[0]:
        need_recreate = True
    else:
        copy_db_to_work(db)
        cols = get_table_cols()
        clean_work_db()
        if not cols:
            need_recreate = True
        else:
            has_new = "source_type" in cols
            has_old = "is_same_party" in cols
            if wv and wv < 115:
                need_recreate = not (has_old and not has_new)
            else:
                need_recreate = not has_new
    if need_recreate:
        if not _native_create_one(pkg, db):
            target = SCHEMA_V94 if (wv and wv < 115) else SCHEMA_V150
            run_su(f"mkdir -p '{os.path.dirname(db)}'")
            clean_work_db()
            con = None
            try:
                con = sqlite3.connect(WORK_DB)
                con.execute("DROP TABLE IF EXISTS cookies")
                con.execute(target)
                con.commit()
                try:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
            except Exception as e:
                log(f"❌ Схема {db}: {e}")
                clean_work_db()
                return False
            finally:
                if con:
                    try:
                        con.close()
                    except Exception:
                        pass
            run_su(f"cp '{WORK_DB}' '{db}'")
            run_su(f"rm -f '{db}-wal' '{db}-shm' '{db}-journal'")
            clean_work_db()
    copy_db_to_work(db)
    con = None
    try:
        con = sqlite3.connect(WORK_DB)
        cur = con.cursor()
        cols_info = cur.execute("PRAGMA table_info(cookies)").fetchall()
        if not cols_info:
            return False
        now_us = _win_to_chrome_time(0)
        defaults = {
            "creation_utc": now_us, "top_frame_site_key": "", "host_key": ".roblox.com",
            "name": ".ROBLOSECURITY", "value": cookie, "encrypted_value": b"",
            "path": "/", "expires_utc": now_us + 946080000000000, "is_secure": 1,
            "is_httponly": 1, "last_access_utc": now_us, "has_expires": 1,
            "is_persistent": 1, "priority": 1, "samesite": -1, "source_scheme": 2,
            "source_port": 443, "is_same_party": 0, "last_update_utc": now_us,
            "source_type": 3, "has_cross_site_ancestor": 1,
        }
        names, vals = [], []
        for _cid, cname, ctype, notnull, dflt, pk in cols_info:
            if cname in defaults:
                names.append(cname)
                vals.append(defaults[cname])
            elif notnull and dflt is None and pk == 0:
                if ctype.upper().startswith("INT"):
                    v = 0
                elif ctype.upper().startswith("BLOB"):
                    v = b""
                else:
                    v = ""
                names.append(cname)
                vals.append(v)
        cur.execute("DELETE FROM cookies WHERE name='.ROBLOSECURITY'")
        cur.execute(f"INSERT INTO cookies ({','.join(names)}) VALUES ({','.join('?' * len(names))})", vals)
        con.commit()
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        con.close()
        con = None
        run_su(f"cp '{WORK_DB}' '{db}'")
        run_su(f"rm -f '{db}-wal' '{db}-shm' '{db}-journal'")
        clean_work_db()
        return True
    except Exception as e:
        log(f"❌ Инъекция {db}: {e}")
        clean_work_db()
        return False
    finally:
        if con:
            try:
                con.close()
            except Exception:
                pass


def inject_cookie_db(pkg, cookie):
    run_su(f"am force-stop {pkg}", timeout=5)
    time.sleep(2)
    run_su(f"mkdir -p /data/data/{pkg}/app_webview/Default/Network")
    wv = webview_version()
    d1 = f"/data/data/{pkg}/app_webview/Default/Cookies"
    d2 = f"/data/data/{pkg}/app_webview/Default/Network/Cookies"
    if run_su(f"test -f '{d1}'")[0]:
        log("📍 Primary cookie DB: Default/Cookies")
    elif run_su(f"test -f '{d2}'")[0]:
        log("📍 Primary cookie DB: Default/Network/Cookies")
    else:
        _native_create_any(pkg)
    ok1 = _inject_cookie_into_db(pkg, d1, cookie, wv)
    ok2 = _inject_cookie_into_db(pkg, d2, cookie, wv)
    fix_ownership(pkg, f"/data/data/{pkg}/app_webview")
    return ok1 or ok2


def inject_prefs_identity(pkg, username, userid):
    prefs = f"/data/data/{pkg}/shared_prefs/prefs.xml"
    ok, content, _ = run_su(f"cat '{prefs}'")
    if not ok or not content:
        content = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map></map>"
    new = content
    for tag in ("username", "displayName"):
        if re.search(rf'<string\s+name="{tag}"\s*>', new):
            new = re.sub(rf'(<string\s+name="{tag}"\s*>)[^<]*(</string>)',
                         lambda m: m.group(1) + username + m.group(2), new)
        else:
            new = new.replace("</map>", f'<string name="{tag}">{username}</string></map>')
    if re.search(r'<long\s+name="userid_long"\s+value="', new):
        new = re.sub(r'(<long\s+name="userid_long"\s+value=")[^"]*("\s*/>)',
                     lambda m: m.group(1) + str(userid) + m.group(2), new)
    else:
        new = new.replace("</map>", f'<long name="userid_long" value="{userid}" /></map>')
    if new != content:
        escaped = new.replace("'", "'\\''")
        run_su(f"printf '%s' '{escaped}' > '{prefs}'")
        fix_ownership(pkg, f"/data/data/{pkg}/shared_prefs")


def inject_pkg(pkg, cookie):
    """Инъекция с проверкой через API. None = не получилось/кука мёртвая."""
    st, uid, uname = fetch_user_info_full(cookie)
    if st == "error":
        time.sleep(5)
        st, uid, uname = fetch_user_info_full(cookie)
    if st == "dead":
        log("☠️ Кука мёртвая (401)")
        return None
    if st != "ok":
        log("⚠️ API недоступен — инъекция пропущена, кука не тронута")
        return None
    if not inject_cookie_db(pkg, cookie):
        if has_session(pkg):
            log(f"✅ {pkg}: БД-ветка не отработала, но сессия записалась")
        else:
            return None
    inject_prefs_identity(pkg, uname, uid)
    if has_session(pkg):
        log(f"✅ {pkg} готов как {uname}")
        return uname
    log("⚠️ Запись не подтвердилась — кука израсходована")
    return "unverified"


def _wipe_one_pkg(pkg):
    run_su(f"am force-stop {pkg}", timeout=5)
    time.sleep(2)
    run_su(f"rm -rf '/data/data/{pkg}/app_webview'", timeout=20)
    for p in [f"/data/data/{pkg}/cache/webview", f"/data/data/{pkg}/cache/WebView"]:
        if run_su(f"test -e '{p}'")[0]:
            run_su(f"rm -rf '{p}'", timeout=15)
    ok, out, _ = run_su(
        "grep -l -i -E 'roblosecurity|cookie|session|userid|user_id|account|token|credential' "
        f"/data/data/{pkg}/shared_prefs/*.xml 2>/dev/null")
    if ok and out:
        for f in out.splitlines():
            run_su(f"rm -f '{f.strip()}'", timeout=5)
    uid = pkg_uid(pkg)
    if uid:
        run_su(f"chown -R {uid}:{uid} /data/data/{pkg}/shared_prefs", timeout=5)


def _hard_reset_main(context=""):
    for i in range(3):
        _wipe_one_pkg(PACKAGE_MAIN)
        if not has_session(PACKAGE_MAIN):
            if i > 0:
                log(f"✅ wipe помог ({context})")
            return True
        log(f"⚠️ Сессия пережила вайп ({context}) — эскалация: pm clear")
        run_su(f"pm clear {PACKAGE_MAIN}", timeout=30)
        time.sleep(3)
    if has_session(PACKAGE_MAIN):
        log(f"🆘 {PACKAGE_MAIN} НЕ ВЫШЕЛ из акка ({context})")
        return False
    return True


def soft_logout_all():
    log("🚪 Мягкий выход из всех пакетов...")
    for pkg in roblox_pkgs():
        _wipe_one_pkg(pkg)
    time.sleep(10)
    log("✅ Все разлогинены")


# ==========================================
# 📁 ФАЙЛЫ КУК (cookies.txt / accounts.txt / архив)
# ==========================================

def save_cookie(cookie, nick, password):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(COOKIES_F, "a") as f:
        f.write(cookie + "\n")
    with open(ACCOUNTS_F, "a") as f:
        f.write(f"{nick}:{password}\n")


def load_cookies_file():
    try:
        if not os.path.exists(COOKIES_F):
            return []
        with open(COOKIES_F) as f:
            return [l.strip() for l in f if l.strip() and len(l.strip()) > 40]
    except Exception:
        return []


def total_sessions():
    n = sum(1 for pkg in get_farm_packages() if has_session(pkg))
    if has_session(PACKAGE_MAIN):
        n += 1
    return n


def archive_and_clear_cookies(reason="сессия завершена"):
    """Отработанные куки → ЛОКАЛЬНЫЙ архив (cookies_used_*.txt), cookies.txt вайпается."""
    raw = load_cookies_file()
    if not raw:
        return 0
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        arch = os.path.join(ARCHIVE_DIR, f"cookies_used_{stamp}.txt")
        with open(arch + ".tmp", "w") as f:
            for c in raw:
                f.write(c + "\n")
        os.replace(arch + ".tmp", arch)
        if os.path.exists(ACCOUNTS_F):
            accs = []
            try:
                with open(ACCOUNTS_F) as f:
                    accs = [l.rstrip("\n") for l in f if l.strip()]
            except Exception:
                pass
            arch_a = os.path.join(ARCHIVE_DIR, f"accounts_used_{stamp}.txt")
            with open(arch_a + ".tmp", "w") as f:
                for l in accs:
                    f.write(l + "\n")
            os.replace(arch_a + ".tmp", arch_a)
    except Exception as e:
        log(f"🧹 ⚠️ Архивация НЕ удалась ({e}) — кукисы СОХРАНЕНЫ на месте")
        return 0
    try:
        with open(COOKIES_F, "w") as f:
            f.truncate(0)
        with open(ACCOUNTS_F, "w") as f:
            f.truncate(0)
        log(f"🧹 ВАЙП ({reason}): {len(raw)} отработанных кук → локальный архив")
    except Exception as e:
        log(f"🧹 ⚠️ Не очистил cookies.txt: {e}")
    return len(raw)


def archive_cookie_list(cookies, reason="инъекция"):
    if not cookies:
        return 0
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(ARCHIVE_DIR, f"cookies_used_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    try:
        with open(path, "a") as f:
            for c in cookies:
                f.write(c + "\n")
    except Exception as e:
        log(f"🧹 ⚠️ Архивация {len(cookies)} кук не удалась: {e}")
        return 0
    drop = {_cookie_hash(c) for c in cookies}
    try:
        remaining = [c for c in load_cookies_file() if _cookie_hash(c) not in drop]
        with open(COOKIES_F + ".tmp", "w") as f:
            for c in remaining:
                f.write(c + "\n")
        os.replace(COOKIES_F + ".tmp", COOKIES_F)
    except Exception as e:
        log(f"🧹 ⚠️ Не обновил cookies.txt: {e}")
    log(f"🧹 ({reason}): {len(cookies)} кук → архив")
    return len(cookies)


def clean_dead_cookies():
    """Живые остаются в cookies.txt, мёртвые выкидываются (API-проверка)."""
    raw = load_cookies_file()
    if not raw:
        return 0, 0
    unique = list(dict.fromkeys(raw))
    dupes = len(raw) - len(unique)
    live, dead = [], 0
    for c in unique:
        if stop_requested():
            live.append(c)
            continue
        st, _uid, _uname = fetch_user_info_full(c)
        time.sleep(1)
        if st in ("ok", "error"):
            live.append(c)
        elif st == "dead":
            dead += 1
    if dead or dupes:
        try:
            with open(COOKIES_F + ".tmp", "w") as f:
                for c in live:
                    f.write(c + "\n")
            os.replace(COOKIES_F + ".tmp", COOKIES_F)
        except Exception as e:
            log(f"🧹 ⚠️ Не записал cookies.txt: {e}")
    log(f"🧹 ЧИСТКА: живых {len(live)}, мёртвых {dead}, дублей {dupes}")
    return len(live), dead + dupes


def take_from_archive_local(need, exclude=None):
    """🆘 КРАЙНИЙ РЕЗЕРВ (локальный архив): живые куки из cookies_used_*.txt."""
    if need <= 0 or not os.path.isdir(ARCHIVE_DIR):
        return []
    excl = {_cookie_hash(c) for c in (exclude or []) if c}
    files = []
    for name in os.listdir(ARCHIVE_DIR):
        if name.startswith("cookies_used_") and name.endswith(".txt"):
            p = os.path.join(ARCHIVE_DIR, name)
            try:
                files.append((os.path.getmtime(p), p))
            except OSError:
                pass
    files.sort(reverse=True)
    taken, tried = [], 0
    for _mt, path in files:
        if len(taken) >= need or tried >= ARCHIVE_SCAN_LIMIT or stop_requested():
            break
        stamp = os.path.basename(path)[len("cookies_used_"):-4]
        accs = []
        acc_path = os.path.join(ARCHIVE_DIR, f"accounts_used_{stamp}.txt")
        if os.path.exists(acc_path):
            try:
                with open(acc_path) as f:
                    accs = [l.strip() for l in f if l.strip()]
            except Exception:
                accs = []
        try:
            with open(path) as f:
                cookies = [l.strip() for l in f if l.strip() and len(l.strip()) > 40]
        except Exception:
            continue
        for i, c in enumerate(cookies):
            if len(taken) >= need or tried >= ARCHIVE_SCAN_LIMIT or stop_requested():
                break
            if _cookie_hash(c) in excl:
                continue
            tried += 1
            st, _uid, uname = fetch_user_info_full(c)
            time.sleep(1)
            if st != "ok":
                continue
            if i < len(accs) and ":" in accs[i]:
                nick, pwd = accs[i].split(":", 1)
            else:
                nick, pwd = (uname or "?"), "?"
            taken.append({"cookie": c, "nick": nick, "pass": pwd})
            excl.add(_cookie_hash(c))
    if taken:
        log(f"🗄 Локальный архив: проверено {tried}, живых взято {len(taken)}")
    return taken


def _rescue_from_files():
    """Спасение кук из cookies.txt + парных ник/пароль из accounts.txt."""
    cookies = load_cookies_file()
    if not cookies:
        return []
    accs = []
    try:
        if os.path.exists(ACCOUNTS_F):
            with open(ACCOUNTS_F) as f:
                accs = [l.strip() for l in f if l.strip()]
    except Exception:
        pass
    tail = accs[-len(cookies):] if accs else []
    out = []
    for i, c in enumerate(cookies):
        if i < len(tail) and ":" in tail[i]:
            np = tail[i].split(":", 1)
        else:
            np = ("?", "?")
        out.append({"cookie": c, "nick": np[0], "pass": np[1]})
    return out


def _write_farm_files(farm_accs):
    """ЕДИНАЯ точка записи cookies.txt/accounts.txt (после добора из пула!)."""
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(COOKIES_F, "w") as f:
            for a in farm_accs:
                f.write(a["cookie"] + "\n")
        with open(ACCOUNTS_F, "w") as f:
            for a in farm_accs:
                f.write(f"{a['nick']}:{a['pass']}\n")
        return True
    except Exception as e:
        log(f"⚠️ Не записал cookies/accounts: {e}")
        return False


# ==========================================
# 📦 ПУЛ НА СЕРВЕРЕ (+ локальный фоллбэк)
# ==========================================

def _server_post(path, payload, timeout=25):
    """POST JSON на сервер → dict или None."""
    if not SERVER:
        return None
    for _attempt in range(2):
        try:
            req = urllib.request.Request(
                f"{SERVER}{path}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": f"FarmRega/{DEVICE_ID}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:
                return None
        except Exception as e:
            log(f"📦 Сервер {path}: {e} (попытка {_attempt + 1}/2)")
            time.sleep(3)
    return None


def server_pool_claim(n, from_status="pool"):
    r = _server_post("/api/pool/claim", {"device_id": DEVICE_ID, "n": n, "from": from_status})
    if not r or not r.get("ok"):
        return []
    return [{"cookie": e["cookie"], "nick": e.get("nick", ""), "pass": e.get("pass", "")}
            for e in (r.get("got") or [])]


def server_report(used=None, dead=None, released=None):
    return _server_post("/api/pool/report",
                        {"device_id": DEVICE_ID, "used": used or [],
                         "dead": dead or [], "released": released or []})


def server_pool_push(accounts):
    """Излишки → пул на сервере. → сколько добавлено."""
    if not accounts:
        return 0
    text = ""
    for a in accounts:
        text += (f"nick: {a.get('nick', '')}\npass: {a.get('pass', '')}\n"
                 f".ROBLOSECURITY={a.get('cookie', '')}\n")
    r = _server_post("/api/pool/add", {"text": text, "to": "pool", "source": DEVICE_ID})
    if r and r.get("ok"):
        return int(r.get("added") or 0)
    return 0


def _pool_load_local():
    try:
        pool = json.loads(Path(POOL_LOCAL_F).read_text())
        return pool if isinstance(pool, list) else []
    except Exception:
        return []


def _pool_save_local(pool):
    try:
        os.makedirs(os.path.dirname(POOL_LOCAL_F), exist_ok=True)
        tmp = POOL_LOCAL_F + ".tmp"
        with open(tmp, "w") as f:
            json.dump(pool, f, ensure_ascii=False)
        os.replace(tmp, POOL_LOCAL_F)
        return True
    except Exception as e:
        log(f"📦 ⚠️ Не записал локальный пул: {e}")
        return False


def pool_take_local(n):
    take = []
    pool = _pool_load_local()
    if pool and n > 0:
        take = pool[:n]
        _pool_save_local(pool[n:])
        log(f"📦 Взял из локального пула: {len(take)}")
    return take


def pool_drain_local_to_server():
    """Локальный пул (нажатый при сбое сети) → сервер."""
    local = _pool_load_local()
    if not local:
        return 0
    added = server_pool_push(local)
    if added and added > 0:
        _pool_save_local([])
        log(f"📦 Локальный пул → сервер: {added}")
        return added
    return 0


def claim_cookies(need):
    """Добор кук: сервер-пул → локальный пул → архив сервера → локальный архив."""
    got, excl = [], set()
    stat = {"pool": 0, "local": 0, "archive": 0, "local_archive": 0}
    if need > 0:
        for a in server_pool_claim(need - len(got)):
            if a["cookie"] and a["cookie"] not in excl:
                got.append(a); excl.add(a["cookie"]); stat["pool"] += 1
        if len(got) < need:
            for a in pool_take_local(need - len(got)):
                if a.get("cookie") and a["cookie"] not in excl:
                    got.append(a); excl.add(a["cookie"]); stat["local"] += 1
        if len(got) < need:
            for a in server_pool_claim(need - len(got), from_status="archive"):
                if a["cookie"] and a["cookie"] not in excl:
                    got.append(a); excl.add(a["cookie"]); stat["archive"] += 1
        if len(got) < need:
            for a in take_from_archive_local(need - len(got), exclude=list(excl)):
                got.append(a); excl.add(a["cookie"]); stat["local_archive"] += 1
        log(f"📦 Добор {need}: пул {stat['pool']}, локальный {stat['local']}, "
            f"архив сервера {stat['archive']}, локальный архив {stat['local_archive']}")
        emit("pool.claim", need=need, **stat)
    return got, stat


def report_chain(claimed, used=None, dead=None, released=None):
    """Отчёт серверу ТОЛЬКО про серверные куки (used→архив, dead→удалить, rest→снять бронь)."""
    cs = {a["cookie"] for a in (claimed or [])}
    if not cs:
        return
    used = list(used or [])
    dead = list(dead or [])
    released = list(released or [])
    u = [c for c in used if c in cs and c not in set(dead)]
    d = [c for c in dead if c in cs]
    rel = [c for c in released if c in cs and c not in u and c not in d]
    if u or d or rel:
        r = server_report(used=u, dead=d, released=rel)
        log(f"📦 Отчёт серверу: used={len(u)} dead={len(d)} released={len(rel)} → {bool(r)}")


# ==========================================
# 🆕 РЕГИСТРАЦИЯ (UI, портрет)
# ==========================================

TAP_CREATE   = (355, 1025)
TAP_YEAR     = (558, 478)
YEAR_TAPS    = 7
TAP_CONFIRM  = (309, 967)
TAP_USERNAME = (143, 528)
TAP_CONTINUE = (338, 881)
TAP_X        = (637, 506)
TAP_DONE     = (362, 615)
TAP_HIDE_KB  = (640, 152)

P_STEP = 3
P_AFTER_TYPE = 2
P_CONTINUE = 10
P_BEFORE_X = 20
P_FIELD_WAIT = 12
P_HIDE_KB = 3
P_REDRAW = 1.5
P_COOKIE_WAIT = 30
P_KEY_CHAR = 0.1
P_PASSWORD_SETTLE = 3

KEYCODE_LOWER = {c: 29 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
KEYCODE_DIGIT = {c: 7 + i for i, c in enumerate("0123456789")}


def gen_nick():
    letters = "".join(random.choice(string.ascii_lowercase) for _ in range(random.randint(8, 11)))
    return letters + str(random.randint(100, 9999))


def gen_pass(_nick):
    while True:
        p = "".join(random.choice(string.ascii_lowercase + string.ascii_uppercase + string.digits)
                    for _ in range(14))
        if any(c.isupper() for c in p) and any(c.islower() for c in p) and any(c.isdigit() for c in p):
            return p


RATE_LIMIT_MARKERS = (
    "too many attempts", "too many tries", "слишком много попыток",
    "слишком много", "try again later", "попробуйте позже",
    "too many requests", "rate limit", "превышено",
)


def check_rate_limit():
    xml = ui_dump()
    if not xml:
        return False
    texts = []
    for m in re.finditer(r'<node[^>]*/?>', xml):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(0)))
        t = html.unescape(attrs.get("text", ""))
        if t:
            texts.append(t)
    txt = " | ".join(texts).lower()
    return any(marker in txt for marker in RATE_LIMIT_MARKERS)


def wait_registration_screen(extra=15):
    deadline = time.time() + extra
    marks = ("sign up", "sign-up", "signup", "log in", "login", "sign in",
             "войти", "регистрац", "создать", "birthday", "дата рожден")
    while time.time() < deadline:
        if stop_requested():
            return False
        xml = ui_dump()
        if xml:
            if "EditText" in xml:
                log("✅ Экран регистрации готов")
                return True
            joined = " | ".join(html.unescape(t).lower()
                                for t in re.findall(r'text="([^"]+)"', xml))
            if any(k in joined for k in marks):
                log("✅ Экран регистрации готов")
                return True
        time.sleep(2)
    log("⚠️ Welcome-экран не дождались — по координатам")
    return False


def get_field_length():
    xml = ui_dump()
    if not xml:
        return -1
    first = -1
    for m in re.finditer(r'<node[^>]*/?>', xml):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(0)))
        if "EditText" not in attrs.get("class", ""):
            continue
        ln = len(html.unescape(attrs.get("text", "")))
        if attrs.get("focused") == "true" or attrs.get("password") == "true":
            return ln
        if first < 0:
            first = ln
    return first


def password_field_visible():
    xml = ui_dump()
    if not xml:
        return False
    return any("EditText" in dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(0))).get("class", "")
               for m in re.finditer(r'<node[^>]*/?>', xml))


def wait_password_field(timeout=P_FIELD_WAIT):
    deadline = time.time() + timeout
    poked = False
    while time.time() < deadline:
        if password_field_visible():
            log("✅ Поле пароля открыто")
            return True
        if not poked and (deadline - time.time()) <= 6:
            tap(*TAP_X)
            poked = True
        time.sleep(1)
    return False


def type_password_batch(password):
    cmds = []
    for ch in password:
        if ch in KEYCODE_LOWER:
            cmds.append(f"input keyevent {KEYCODE_LOWER[ch]}")
        elif ch in KEYCODE_DIGIT:
            cmds.append(f"input keyevent {KEYCODE_DIGIT[ch]}")
        elif ch.isupper():
            code = KEYCODE_LOWER.get(ch.lower())
            if code:
                cmds.append(f"input keycombination 59 {code}")
        else:
            cmds.append(f"input text '{ch}'")
        cmds.append(f"sleep {P_KEY_CHAR}")
    run_su("; ".join(cmds), timeout=60)


def type_password_reliable(password):
    type_text(password, timeout=30)
    time.sleep(P_PASSWORD_SETTLE)
    for _ in range(3):
        got = get_field_length()
        if got == -1 or got >= len(password):
            return True
        type_text(password[got:], timeout=20)
        time.sleep(2)
    got = get_field_length()
    if got != -1 and 0 < got < len(password):
        log("⚠️ Пароль вводится плохо — batch-режим")
        select_all_delete()
        type_password_batch(password)
        time.sleep(3)
    return True


def hide_keyboard():
    tap(*TAP_HIDE_KB)
    time.sleep(P_HIDE_KB)


def registration_attempt(attempt_num):
    nick = gen_nick()
    password = gen_pass(nick)
    log(f"— ПОПЫТКА {attempt_num} | ник: {nick}")

    if not _hard_reset_main(f"перед попыткой {attempt_num}"):
        raise RuntimeError("wipe PKG_MAIN failed — проверить su!")
    launch()
    wait_registration_screen()
    tap(*TAP_CREATE)
    time.sleep(P_STEP)

    year_cmds = "; ".join(
        f"input tap {TAP_YEAR[0]} {TAP_YEAR[1]}; sleep 0.9" for _ in range(YEAR_TAPS))
    run_su(year_cmds, timeout=YEAR_TAPS * 2 + 10)

    tap(*TAP_CONFIRM)
    time.sleep(P_STEP)
    tap(*TAP_USERNAME)
    time.sleep(1.5)
    type_text(nick, timeout=20)
    time.sleep(P_AFTER_TYPE)
    hide_keyboard()
    tap(*TAP_CONTINUE)
    time.sleep(P_CONTINUE)

    if check_rate_limit():
        log("🚫 RATE-LIMIT после Продолжить!")
        return None, True

    time.sleep(P_BEFORE_X)
    tap(*TAP_X)

    if check_rate_limit():
        log("🚫 RATE-LIMIT после крестика!")
        return None, True

    if not wait_password_field(P_FIELD_WAIT):
        log("⚠️ Поле пароля не появилось — ввожу вслепую")

    type_password_reliable(password)
    hide_keyboard()
    time.sleep(P_REDRAW)
    tap(*TAP_DONE)
    time.sleep(P_STEP)

    if check_rate_limit():
        log("🚫 RATE-LIMIT после Готово!")
        return None, True

    cookie = extract_cookie(wait=P_COOKIE_WAIT)
    if not cookie:
        log("❌ Кука не появилась")
        if has_session(PACKAGE_MAIN):
            log(f"⚠️ Регистрация похоже УСПЕШНА, но куку не вытащил — акк {nick} пропадёт!")
        if check_rate_limit():
            return None, True
        return None, False

    st, uid, uname = fetch_user_info_full(cookie)
    if st == "dead":
        log("❌ Кука не прошла API (401)")
        return None, False
    if st == "error":
        log("⚠️ API недоступен — сохраняю куку с локальным ником")
        return {"cookie": cookie, "nick": nick, "pass": password}, False

    log(f"✅ Акк готов: {uname}")
    return {"cookie": cookie, "nick": uname, "pass": password}, False


def collect_cookies(target_total):
    """40 попыток = 4 раунда × 10, паузы 15 мин. Возвращает накопленное."""
    kept = []
    total_attempts = MAX_ROUNDS * REG_ATTEMPTS
    log(f"🎯 Рега: {total_attempts} попыток | цель {target_total}")
    done = 0
    aborted = False
    for round_num in range(1, MAX_ROUNDS + 1):
        if stop_requested():
            break
        log(f"🔁 Раунд {round_num}/{MAX_ROUNDS} | сделано {done} | аккаунтов {len(kept)}/{target_total}")
        rate_limited = False
        consec_errors = 0
        for attempt in range(1, REG_ATTEMPTS + 1):
            if len(kept) >= target_total or stop_requested():
                break
            done += 1
            result, rl = None, False
            raised_exc = False
            try:
                result, rl = registration_attempt(done)
            except Exception:
                log("💥 Попытка упала с исключением")
                result, rl = None, False
                consec_errors += 1
                raised_exc = True
            else:
                consec_errors = 0
            finally:
                kill_main_only()
                if not _hard_reset_main(f"после попытки {done}"):
                    log("⚠️ Ресет после попытки не подтвердился")
            emit("rega.attempt", n=done, ok=bool(result), nick=(result or {}).get("nick", ""))
            if raised_exc and consec_errors >= 3:
                log("🛑 3 подряд упавших попытки — мягкий стоп")
                aborted = True
                break
            if rl:
                rate_limited = True
                break
            if result:
                kept.append(result)
                save_cookie(result["cookie"], result["nick"], result["pass"])
                log(f"🏅 Аккаунт {len(kept)}/{target_total}: {result['nick']}")
        if aborted or len(kept) >= target_total or stop_requested():
            break
        if round_num < MAX_ROUNDS:
            pause_min = RATE_LIMIT_PAUSE // 60 if rate_limited else ROUND_PAUSE_MIN
            log(f"⏸️ Пауза {pause_min} мин..." + (" (RATE-LIMIT)" if rate_limited else ""))
            if interruptible_sleep(pause_min * 60, step=10):
                log("🛑 Стоп: пауза регы прервана")
                break
    log(f"🏁 Рега завершена: попыток {done}/{total_attempts} | аккаунтов {len(kept)}")
    ui_cache_clear()
    return kept


def _inject_main_priority(cookies):
    """🥇 Кука №1 → MAIN (Delta): байпасу нужна залогиненная Дельта."""
    if not REG_MAIN_FIRST or not cookies:
        return cookies
    c = cookies[0]
    res = inject_pkg(PACKAGE_MAIN, c)
    if res and res != "unverified":
        archive_cookie_list([c], "main priority")
        log(f"🥇 MAIN вошёл первым: {res}")
        return cookies[1:]
    if res == "unverified":
        archive_cookie_list([c], "main unverified")
        return cookies[1:]
    st2, _u, _n = fetch_user_info_full(c)
    time.sleep(1)
    if st2 == "dead":
        archive_cookie_list([c], "main dead")
        return cookies[1:]
    if has_session(PACKAGE_MAIN):
        log("🔒 MAIN: кука частично записалась — в клоны НЕ отдаём")
        archive_cookie_list([c], "main partial-write")
        return cookies[1:]
    log("⚠️ MAIN: инъекция не прошла (сеть) — кука пойдёт клонам")
    return cookies


def do_injection(cookies):
    if not cookies:
        log("☠️ Входить нечем")
        return 0, []
    pkgs = get_farm_packages()
    seen, deduped = set(), []
    for c in cookies:
        h = _cookie_hash(c)
        if h not in seen:
            seen.add(h)
            deduped.append(c)
    cookies = deduped
    log(f"💉 Вход по кукам в КЛОНЫ: пакетов {len(pkgs)} | кук {len(cookies)}")
    ok_count, consumed, recycle = 0, [], []
    pairs = list(zip(pkgs, cookies))
    leftover = cookies[len(pairs):]
    for pkg, c in pairs:
        if stop_requested():
            recycle.append(c)
            continue
        res = inject_pkg(pkg, c)
        if res == "unverified":
            consumed.append(c)
        elif res:
            ok_count += 1
            consumed.append(c)
            log(f"🎉 ЗАШЛО: {pkg} → {res}")
        else:
            st2, _u, _n = fetch_user_info_full(c)
            time.sleep(1)
            if st2 == "dead":
                consumed.append(c)
                log(f"☠️ Не зашло (кука мертва): {pkg}")
            else:
                recycle.append(c)
                log(f"⚠️ Не зашло (кука НЕ тронута): {pkg}")
    for c in leftover:
        st2, _u, _n = fetch_user_info_full(c)
        time.sleep(1)
        if st2 == "dead":
            consumed.append(c)
        else:
            recycle.append(c)
    archive_cookie_list(consumed, "инъекция завершена")
    return ok_count, recycle


# ==========================================
# ▶️ ФАЗА: РЕГИСТРАЦИЯ + ВХОД (пул на сервере)
# ==========================================

def phase_registration_and_login(target):
    log("=" * 50)
    log("🤖 ФАЗА: РЕГИСТРАЦИЯ")
    log("=" * 50)
    set_portrait()
    wake_screen()
    archive_and_clear_cookies("перед стартом новой сессии")
    soft_logout_all()
    if stop_requested():
        # фарм ⏹ (полный стоп, v0.13): остановленной реге реармить фарм НЕЛЬЗЯ,
        # иначе остановленный фарм сам поднимется. Реармит только завершение/падение.
        emit("rega.stop", phase="before_reg")
        return

    kept = []
    try:
        kept = collect_cookies(target)
    except Exception as e:
        log(f"💥 Рега упала целиком: {e} → спасаю куки из файлов")
    if stop_requested():
        # фарм ⏹ (полный стоп) — см. before_reg: реарма нет
        emit("rega.stop", phase="after_reg")
        return

    merged = {}
    for a in list(kept) + _rescue_from_files():
        c = a.get("cookie")
        if c and c not in merged:
            merged[c] = a
    all_accs = list(merged.values())

    farm_accs = all_accs[:DEFAULT_TARGET]
    extra_accs = all_accs[DEFAULT_TARGET:]
    log(f"🔀 Своих: {len(all_accs)} | ферма: {len(farm_accs)} | излишки: {len(extra_accs)}")

    # 📦 излишки → пул НА СЕРВЕРЕ (фоллбэк: локальный пул)
    if extra_accs:
        pool_drain_local_to_server()
        added = server_pool_push(extra_accs)
        if added > 0:
            log(f"📦 Излишки → пул сервера: +{added}")
            emit("pool.push", added=added)
        else:
            added = 0
            pool = _pool_load_local()
            seen = {e.get("cookie") for e in pool}
            for a in extra_accs:
                if a.get("cookie") and a["cookie"] not in seen:
                    seen.add(a["cookie"])
                    pool.append({"nick": a.get("nick", ""), "pass": a.get("pass", ""),
                                 "cookie": a["cookie"],
                                 "ts": datetime.now().isoformat(" ", timespec="seconds"),
                                 "from": DEVICE_ID})
                    added += 1
            if added and _pool_save_local(pool):
                log(f"📦 Сервер недоступен — излишки в ЛОКАЛЬНОМ пуле: +{added} (перелью позже)")
            else:
                log("🆘🆘🆘 ИЗЛИШКИ НЕ СОХРАНЕНЫ НИ КУДА! Восстанови по паролям:")
                for a in extra_accs:
                    log(f"   🆘 nick: {a['nick']} | pass: {a['pass']}")

    # 🔁 НЕДОБОР → бронь из пула (сервер → локальный → архивы)
    claimed_accs = []
    if len(farm_accs) < DEFAULT_TARGET:
        need = DEFAULT_TARGET - len(farm_accs)
        log(f"🔁 Недобор {need} → добор из пула/архива...")
        claimed_accs, _stat = claim_cookies(need)
        claimed_accs = claimed_accs[:need]
        if claimed_accs:
            log(f"🔁 Добрал из пула: {len(claimed_accs)}")
            farm_accs.extend(claimed_accs)
        else:
            log(f"⚠️ Пул пуст — ферма {len(farm_accs)}/{DEFAULT_TARGET}")

    if farm_accs:
        _write_farm_files(farm_accs)

    log("🤖 ФАЗА: ЧИСТКА")
    clean_dead_cookies()

    login_cookies = list(dict.fromkeys(load_cookies_file()))

    log("🤖 ФАЗА: ИНЪЕКЦИЯ")
    soft_logout_all()
    login_cookies = _inject_main_priority(login_cookies)
    _okc, recycle = do_injection(login_cookies)
    if recycle:
        archive_cookie_list(recycle, "recycle — повторно не используем")

    # 🧹 серверные куки: used → архив сервера, released → снять бронь
    claimed_cookies = [a["cookie"] for a in claimed_accs]
    arch_files = []
    try:
        for name in os.listdir(ARCHIVE_DIR):
            if name.startswith("cookies_used_"):
                with open(os.path.join(ARCHIVE_DIR, name), errors="replace") as f:
                    arch_files += [l.strip() for l in f if l.strip()]
    except Exception:
        pass
    archived_set = {_cookie_hash(c) for c in arch_files}
    alive_now = set(load_cookies_file())
    used_srv = [c for c in claimed_cookies if _cookie_hash(c) in archived_set]
    released_srv = [c for c in claimed_cookies if c not in used_srv and c in alive_now]
    report_chain(claimed_accs, used=used_srv, dead=[], released=released_srv)

    state["last_reg_time"] = time.time()
    if kept or claimed_accs:
        state["last_reg_date"] = datetime.now().strftime("%Y-%m-%d")
    save_state()
    ui_cache_clear()
    if stop_requested():
        # фарм ⏹ добил регу на финише — rega.stop, БЕЗ реарма фарм
        emit("rega.stop", phase="before_done")
        return
    sessions = total_sessions()
    log(f"🏁 Реги завершена: сессий {sessions}")
    emit("rega.done", accounts=len(all_accs), farm=len(farm_accs),
         pool_push=len(extra_accs), claimed=len(claimed_accs), sessions=sessions)
    rearm_farm()


# ==========================================
# 🔍 РЕЖИМ CHECK: проверка кук + починка из пула/архива
# ==========================================

def cookie_check():
    """Все телефоны проверяются: вылетела кука → вход из пула, пул пуст → архив."""
    log("🍪 CHECK: проверка кук на всех пакетах")
    emit("check.start")
    set_portrait()
    wake_screen()
    pkgs = [PACKAGE_MAIN] + get_farm_packages()
    empty_pkgs, dead_pairs = [], []          # dead_pairs: (pkg, старая_кука)
    for pkg in pkgs:
        if stop_requested():
            break
        if not has_session(pkg):
            log(f"⚠️ {pkg}: сессии нет")
            empty_pkgs.append(pkg)
            continue
        c = None
        for db in cookie_db_candidates(pkg):
            c = _read_roblosecurity(db)
            if c:
                break
        if c:
            st, _u, _n = fetch_user_info_full(c)
            time.sleep(1)
            if st == "dead":
                log(f"☠️ {pkg}: кука вылетела (401)")
                dead_pairs.append((pkg, c))
            elif st == "error":
                log(f"⚠️ {pkg}: API недоступен — не трогаю")
        else:
            log(f"⚠️ {pkg}: куку не вытащил, но сессия есть — не трогаю")

    need = len(empty_pkgs) + len(dead_pairs)
    emit("check.scanned", packages=len(pkgs), empty=len(empty_pkgs), dead=len(dead_pairs))
    if need == 0:
        log("✅ CHECK: все куки живы")
        emit("check.done", replaced=0, need=0)
        return

    log(f"🛠 Починка: пустых {len(empty_pkgs)}, мёртвых {len(dead_pairs)}")
    # старые мёртвые: чистим из cookies.txt (серверу отчёт — только про свои куки ниже)
    dead_cookies = [c for _p, c in dead_pairs]
    drop = {_cookie_hash(c) for c in dead_cookies}
    try:
        remaining = [c for c in load_cookies_file() if _cookie_hash(c) not in drop]
        with open(COOKIES_F + ".tmp", "w") as f:
            for c in remaining:
                f.write(c + "\n")
        os.replace(COOKIES_F + ".tmp", COOKIES_F)
    except Exception:
        pass

    claimed, _stat = claim_cookies(need)
    used, dead_srv, released = [], [], [a["cookie"] for a in claimed]
    fixed = 0
    fix_list = [p for p, _c in dead_pairs] + empty_pkgs
    for pkg in fix_list:
        if stop_requested():
            break
        cookie = None
        while claimed:
            cand = claimed.pop(0)
            st, _u, _n = fetch_user_info_full(cand["cookie"])
            time.sleep(1)
            if st == "dead":
                dead_srv.append(cand["cookie"])
                log("☠️ Кука из пула мёртвая — беру следующую")
                continue
            if st == "error":
                released.append(cand["cookie"])
                log("⚠️ API недоступен — куку не трогаю")
                continue
            cookie = cand
            released[:] = [c for c in released if c != cand["cookie"]]
            break
        if not cookie:
            log(f"🆘 {pkg}: замен нет (пул и архив пусты)")
            continue
        uname = inject_pkg(pkg, cookie["cookie"])
        if uname in (None, "unverified"):
            st2, _u, _n = fetch_user_info_full(cookie["cookie"])
            time.sleep(1)
            if st2 == "dead":
                dead_srv.append(cookie["cookie"])
            elif uname is None:
                released.append(cookie["cookie"])
            continue
        # 🎉 вошли: сохраняем локально + перезапускаем пакет в фарм-плейс
        save_cookie(cookie["cookie"], cookie.get("nick") or uname, cookie.get("pass") or "?")
        used.append(cookie["cookie"])
        fixed += 1
        deep_link_start(pkg)
        time.sleep(2)
        emit("check.replace", pkg=pkg, nick=uname)
        log(f"🎉 {pkg}: починен ({uname})")

    report_chain(claimed + [{"cookie": c} for c in used + dead_srv + released],
                 used=used, dead=dead_srv, released=released)
    log(f"🏁 CHECK готов: починено {fixed}/{need}")
    emit("check.done", replaced=fixed, need=need, dead_removed=len(dead_srv))


# ==========================================
# ▶️ ФАРМ ПОСЛЕ РЕГИ (watchdog поднимет)
# ==========================================

def rearm_farm():
    """farm=running в services_state.json → клиентский watchdog поднимет фарм."""
    f = BASE / "info" / "services_state.json"
    try:
        try:
            data = json.loads(f.read_text())
        except Exception:
            data = {}
        data["farm"] = "running"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(f)
        log("▶️ farm: desired=running — watchdog поднимет фарм")
    except Exception as e:
        log(f"⚠️ rearm_farm: {e}")


# ==========================================
# ▶️ MAIN
# ==========================================

LOCK_FILE = BASE / "info" / "rega.lock"
_LOCK_FP = [None]          # держим открытым до конца процесса — иначе flock отпустит


def _acquire_lock():
    """Одиночный экземпляр рега-сервиса (принцип v18.8 flock).
    False = рега уже идёт (второй процесс выйдет с кодом 99)."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fp = open(LOCK_FILE, "w")
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(os.getpid()))
        fp.flush()
        _LOCK_FP[0] = fp
        return True
    except OSError:
        return False


def main():
    signal.signal(signal.SIGTERM, _sigterm)
    mode = "rega"
    if len(sys.argv) > 1:
        a = sys.argv[1].strip().lower()
        if a in ("check", "cookie", "c"):
            mode = "check"
    if not _acquire_lock():
        log("🛑 Рега/check уже идёт (лок info/rega.lock) — выхожу (код 99)")
        sys.exit(99)
    log(f"🆕 REGA SERVICE START | режим: {mode} | device: {DEVICE_ID} | сервер: {SERVER or '❌'}")
    load_state()
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    wake_lock()

    if mode == "check":
        try:
            cookie_check()
        except Exception as e:
            log(f"💥 check упал: {e}")
            emit("check.fail", error=str(e)[:200])
        return

    emit("rega.start", target=DEFAULT_TARGET, device=DEVICE_ID)
    try:
        phase_registration_and_login(DEFAULT_TARGET)
    except Exception as e:
        log(f"💥 Рега упала: {e}")
        emit("rega.fail", error=str(e)[:200])
        rearm_farm()


if __name__ == "__main__":
    main()
