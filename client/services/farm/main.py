#!/usr/bin/env python3
"""
🤖 Roblox Farm v16.2 — СЕРВИС ФЕРМЫ (services/farm/main.py)

Этап 1: фарм интегрирован в систему как чёрный ящик.
Запускается ТОЛЬКО через ProcessManager (service.start farm),
stdout уходит в logs/services/farm.log.

Адаптации под систему (логика v16.2 не менялась):
- ✅ State в info/farm_state.json (атомарная запись) — переживает ребуты/апдейты.
    Один файл — один писатель: farm_state.json пишет ТОЛЬКО фарм, клиент читает.
- ✅ Обработчик SIGTERM — корректная остановка через дашборд (farm ⏹).
- ✅ requests → urllib (stdlib): на телефоне не нужен pip install.
- ✅ Устойчивый поиск su (PATH может быть побит root-стражем).
- ✅ Компактный лог мониторинга: одна строка на проверку (ротации логов нет).
- ✅ Ноль связи с сервером: фарм ничего не знает про сервер и наоборот.

Этап 2 (события):
- ✅ Фарм пишет события в info/farm_events.jsonl (одна JSON-строка на событие).
    Клиент читает их (outbox) и доставляет на сервер → SQLite. Фарм про сервер
    по-прежнему НЕ знает: только файл, принцип «один файл — один писатель».

v0.9 (чистая остановка):
- ✅ Остановка фарма (farm ⏹ / полный стоп / Ctrl+C) закрывает ВСЕ роблоксы
    (com.roblox*) и браузеры, которые фарм сам открывает при байпасе.
    Телефон после остановки остаётся чистым, события farm.stop несёт closed=N.

v0.11 (куки-гейт):
- ✅ Байпас и фарм только при живых куках: перед циклом считаем сессии
    (has_session по WebView DB — как в v18.8). Кук нет (0 сессий) → байпас
    НЕ делается: фарм сам запускает авторегистрацию (services/rega, flock —
    двойной запуск невозможен), ждёт её и только потом идёт обычный цикл.
- ✅ Рега не дала кук → пауза 30 мин и новая попытка (само-восстановление).

v0.12 (куки-гейт v2 — клоны):
- ✅ Гейт смотрит не «0 сессий вообще», а на КАЖДУЮ часть фермы:
    нет куки на Дельте (main) → байпас не работает → рега;
    все клоны пустые → фармить нечем → рега.
    Раньше кука Дельты маскировала пустые клоны и фарм гонял байпас впустую.
- ✅ Частичная убыль (например 1 клон из 4) регу не поднимает — фарм работает
    на том, что есть, а починку делают check (пул/архив, каждые 30 мин)
    и ежедневная рега в 03:00. Так сломанный клон не гоняет регу по кругу.

v0.13 (полный стоп):
- ✅ farm ⏹ — теперь ПОЛНЫЙ стоп: глушит и регу (services/rega, включая check):
    SIGTERM → 8с на мягкий выход → SIGKILL + чистка pid-файла. Раньше фарм
    глох, а рега продолжала работать и после завершения ещё и поднимала фарм.
- ✅ Рега при принудительной остановке шлёт rega.stop и БОЛЬШЕ НЕ реармит фарм
    (реармит только завершение/падение) — farm ⏹ больше не отменяется сам.
- ✅ Гейт: если спавн рега вышел с кодом 99 (лок держит другая рега/check) —
    фарм ждёт освобождения лока (flock-проба) и пробует ещё раз.

v0.14 (байпас v18.8 + рега 20 попыток):
- ✅ Байпас портирован ИЗ СКРИПТА ХОЗЯИНА v18.8 без упрощений:
    9 попыток (6 обычных + 3 с двойным кликом CLOSE_AD), точные UI-координаты
    в ландшафте, ZEN-API с полным разбором ответа (ссылка/ключ/429-ретраи),
    буфер в 3 способа (termux-api → service call parcel → вставка+дамп экрана),
    открытие длинной ссылки в 4 фоллбэка (am start → paste → чанки → посимвольно),
    чтение ключа в 4 способа, строгая проверка записи ключа (read-back).
- ✅ Рега = 20 попыток ВСЕГДА (2×10), отдых 15 мин после каждых 10 — НЕ важно,
    удачные или нет; излишки (>5) → общий пул НА СЕРВЕРЕ; телефоны, у которых
    из 20 попыток меньше 5 удачных, добирают кук из этого пула (→ архив).

v0.15 (байпас по кнопке + перезапуск клонов при сборе):
- ✅ Задача bypass.run (клиент) → флаг info/bypass_force.json → фарм в ≤30с делает
    ПОЛНЫЙ цикл v18.8 БЕЗ рестарта сервиса (Delta → реклама → ZEN-API → ключ →
    license + read-back). Фарм не жил → клиент сам его стартует.
- ✅ Мониторинг прерывается флагом байпаса — и при фарме, и при сборе;
    после байпаса сбор продолжится на остаток окна.
- ✅ Вылетевший клон (окно не видно в dumpsys) → force-stop → 15с → запуск
    СРАЗУ В ПЛЕЙС (roblox://experiences/start?placeId=...) — как в v18.8:
    и во время обычного фарма, и во время сбора (в плейс приватки).

v16.2 (оригинал):
- ✅ ВСЕГДА перезаписывает /storage/emulated/0/Delta/Autoexecute/1.lua при запуске
- ✅ Прямой запрос к ZEN-API
- ✅ 24-часовой таймер байпаса
- ✅ Записывает ключ напрямую в файл license (без ввода через экран)
- ✅ 3 тапа по рекламе для получения ссылки
- ✅ Во время БАЙПАСА запуск СРАЗУ в плейс (без главного меню)
- ✅ Во время ФАРМЫ: ожидание 15 сек -> прямой запуск в плейс
- ✅ com.roblox.client запускается ТОЛЬКО при байпасе, ферма его игнорирует
- ✅ Мониторинг фермы каждые 30 сек — если окно не видно, пакет перезапускается
- ✅ Если пакет вылетел, перед перезапуском тоже ожидание 15 сек

v0.20 (🛡 БЕЗОПАСНЫЙ СБОР-ТРЕЙД + kill-switch регы):
- ✅ РЕГА АККОВ — kill-switch: клиент пишет info/rega_switch.json (задача
    rega.switch с сервера: тумблер дашборда + hello-sync). Файла нет = ВЫКЛЮЧЕНА
    (безопасный режим по умолчанию — чтобы случайно не удалить/не перезаписать
    акки с лутом). При отключенной реге handle_no_cookies НЕ регистрирует:
    пишет событие rega.blocked и ждёт (фарм клонами продолжается).
- ✅ СБОР УРОЖАЯ v2 = БЕЗОПАСНЫЙ ТРЕЙД (по скриптам хозяина):
    • на время окна автоэкзекют Дельты = treid.lua (масс-трейд ВСЕГО лута
      целевым аккам-сборщикам, качается с GitHub, кэш info/harvest_treid.lua);
    • приватные сервера — ТОЛЬКО из id.txt хозяина (32-симв. share-коды,
      кэш info/harvest_ids.txt); клоны расходятся по привяткам по кругу;
    • вылетевший клон возвращается НА СВОЙ приватный сервер (grace 90с на
      долёт через браузерный редирект);
    • после окна — kill + ВОССТАНОВЛЕНИЕ фарм-скрипта в автоэкзекюте (любой
      исход: окно кончилось / байпас / падение — finally);
    • 🛡 АККИ НЕ ТРОГАЕМ: ни куки, ни WebView — только трейд предметов.
      Нет целей (сборщики офлайн) → treid.lua сам ждёт, лут остаётся на фармере;
    • treid.lua недоступен (сеть+кэш) → сбор на этом телефоне ОТМЕНЯЕТСЯ
      (не гоняем фарм-скрипт в приватки впустую);
    • куки-чек перед стартом: хоть один клон с кукой обязателен (иначе в
      приватку не зайти).
- ✅ Окно сбора проверяется В НАЧАЛЕ цикла (ДО куки-гейта): сбору нужны
    только куки КЛОНОВ, а гейт требует ещё живой акк Дельты — раньше
    мёртвый main мог блокировать сбор навсегда (с отключенной регой — тем более).
- ✅ Новый сервис-компаньон services/collector/main.py — телефон-сборщик
    (порт bank.py хозяина): автоэкзекют = collet.lua (авто-приём трейдов),
    полный байпас v18.8 (импорт этого модуля), те же приватки из id.txt.

v0.21 (🛠 ФИКС ЗАХОДА В ПРИВАТКИ — алгоритм из РАБОЧЕГО скрипта хозяина):
- ✅ СБОР НЕ РАБОТАЛ: фермеры не заходили на приватные сервера. Причина —
    фолбэк после несработавшей share-ссылки вёл В ОБЫЧНЫЙ ПЛЕЙС
    (roblox://experiences/start?placeId=...) БЕЗ кода привата: у клонов
    am start с https-ссылкой часто не отрабатывает → фермеры уходили в
    публичный плейс, трейд не начинался.
- ✅ Теперь КАК В РАБОЧЕМ СКРИПТЕ (collet(1).py):
    1) share-ссылка https://www.roblox.com/share?code=...&type=Server;
    2) не сработала → ПРЯМОЙ deep link В ПРИВАТКУ
       roblox://experiences/start?placeId=...&privateServerLinkCode=...
       (без браузера, сразу в приватный сервер).
- ✅ Единый хелпер am_start_link() + private_deep_link(): один и тот же
    алгоритм в launch_farmers_private, restart_pkg (вылетевший клон
    возвращается НА СВОЮ приватку) и в сервисе collector.

v0.22 (🔥 ЛОКАЛЬНЫЕ КОДЫ ПРИВАТОК — фолбэк как в РАБОЧЕМ скрипте хозяина):
- ✅ ГЛАВНАЯ ПРИЧИНА «во время сбора запускает в просто плейс»: если телефон
    не смог скачать id.txt с GitHub raw (сеть/блокировка) и кэш пуст, кодов
    привяток НЕ было вообще → срабатывала ветка launch_roblox_light_farm() —
    фермеров запускало В ОБЫЧНЫЙ ПЛЕЙС. В рабочем скрипте хозяина (collet(1).py)
    такого НЕ бывает: там 4 кода привяток ЗАШИТЫ В САМ СКРИПТ
    (PRIVATE_SHARE_CODES) как локальный фолбэк, поэтому он работает всегда.
- ✅ Теперь ТОЧНО ТАК ЖЕ: PRIVATE_SHARE_CODES_FALLBACK — зашитые share-коды
    привяток из id.txt хозяина. Порядок получения кодов: GitHub id.txt →
    кэш info/harvest_ids.txt → ЗАШИТЫЕ КОДЫ (привятки есть ВСЕГДА, ветки
    «запуск в обычный плейс» во время сбора больше НЕТ).
- ✅ То же в сервисе collector (get_codes) — сборщик тоже не падает в плейс.

v0.24 (🌾 СБОР = HOLD — сидим в приватках до кнопки «НОВЫЙ ЦИКЛ»):
- ✅ ПО ПРОСЬБЕ ХОЗЯИНА («сделай пока что просто»): когда идёт сбор — фармеры
    заходят на приватный сервер с нужным луа скриптом (treid.lua) и НЕ ВЫХОДЯТ,
    пока хозяин в панели не нажмёт «НОВЫЙ ЦИКЛ». Только тогда сервер снимает
    окно, гасит фарм, запускает регу акков — а рега по завершении сама ставит
    фарм. Никаких «2 пачек по 20 мин» и авто-выхода из сбора.
- ✅ harvest_window() теперь понимает hold: True (окно без срока, пишет клиент
    v0.24 по команде сервера v0.8). run_harvest_session в HOLD-режиме мониторит
    привятки БЕСКОНЕЧНО (до исчезновения окна): вылетевший клон возвращается
    на свой сервер, байпас по кнопке работает как раньше.
- ✅ Лог/события честно пишут «HOLD — до кнопки НОВЫЙ ЦИКЛ» вместо гигантских
    минут.

v0.25 (🚫 КЛИЕНТ НЕ НАЗНАЧАЕТ СЕБЕ ЗАДАЧИ — байпас только с сервера):
- ✅ ПО ПРОСЬБЕ ХОЗЯИНА («клиент должен выполнять только задачи с сервера,
    а не сам назначать себе»; факт 25.10: «в 20 мин он начал делать байпас,
    хотя я до этого всё остановил»): УДАЛЁН авто-байпас по кулдауну 24ч.
    Раньше главный цикл при устаревшем ключе (last_key_time > 24ч) САМ
    запускал run_bypass_cycle() БЕЗ всякой задачи с сервера — ровно это и
    видел хозяин. Теперь байпас выполняется ТОЛЬКО по явной задаче сервера
    bypass.run (кнопка 🔓 в панели → bypass_force.json). Возраст ключа
    ни на что не влияет: нет задачи — байпас не запускается, фарм работает.
- ✅ FORCE_BYPASS («байпас каждый цикл») больше НЕ ДЕЙСТВУЕТ — тот же
    принцип: никаких самоназначенных задач, только сервер.
"""
import os
import sys
import json
import time
import re
import html
import shutil
import signal
import fcntl
import sqlite3
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================

ZEN_API_KEY = "bf1816b1-89df-4729-8d0a-654f022330f9"
ZEN_API_URL = "https://api.izen.lol/v1/bypass"

DELTA_AUTOEXEC_PATH = "/storage/emulated/0/Delta/Autoexecute/1.lua"
DELTA_LICENSE_PATH = "/storage/emulated/0/Delta/Internals/Cache/license"
DELTA_LUA_CONTENT = "loadstring(game:HttpGet('https://raw.githubusercontent.com/gleb228666999/test/refs/heads/main/1.lua'))()"

FARM_CYCLE_SECONDS = 14400

# 🔍 Проверка фермы
FARM_CHECK_INTERVAL = 30      # Как часто проверять окна фермы
FARM_PRELAUNCH_DELAY = 15     # Задержка перед обычным запуском фермера
FARM_RESTART_DELAY = 15       # Задержка перед перезапуском вылетевшего фермера

# 🚫 v0.25: авто-байпас по кулдауну УДАЛЁН — байпас ТОЛЬКО по задаче сервера
# (bypass.run → bypass_force.json). Константы оставлены для совместимости,
# НИЧЕГО не включают и в логике не используются.
FORCE_BYPASS = False
BYPASS_COOLDOWN = 86400

# --- 🖱️ координаты байпаса (ландшафт) и задержки — ИЗ v18.8, БЕЗ изменений ---
LINK_TAP       = (1000, 470)
CLOSE_TRANSL_1 = (1126, 666)
TRIGGER_AD     = (600, 700)
CLOSE_AD       = (1240, 540)
CONTINUE_1     = (600, 700)
GOOGLE_ROW     = (470, 100)
COPY_LINK      = (1023, 213)

CONTINUE_KEY   = (530, 530)
CLOSE_TRANSL_2 = (1126, 666)
COPY_CODE      = (615, 680)

OMNIBOX_TAP    = (640, 60)

UI_INITIAL_DELAY  = 20     # ждём загрузки MM2 в Дельте
COPY_SETTLE_DELAY = 4      # даём ссылке время скопироваться
DBLCLICK_GAP      = 0.5    # пауза между двумя кликами CLOSE_AD

UI_STEP_DELAYS = {
    "LINK_TAP": 7, "SET_LANDSCAPE": 2, "CLOSE_TRANSL_1": 1,
    "TRIGGER_AD": 1, "CLOSE_AD": 1, "CONTINUE_1": 2,
    "GOOGLE_ROW": 1, "COPY_LINK": 3, "OPEN_ZEN_LINK": 30,
    "CONTINUE_KEY": 6, "CLOSE_TRANSL_2": 1, "COPY_CODE": 3,
}

BYPASS_CLICK_RETRIES    = 6   # обычных попыток
BYPASS_DBLCLICK_RETRIES = 3   # с двойным кликом CLOSE_AD (6+3 = 9)

# 🔑 ключ лицензии (FREE_xxx / XXX_xxxxxxxxxxxxxxxx)
KEY_RE = re.compile(r'\b(FREE_[A-Za-z0-9_\-]{8,}|[A-Z]{2,10}_[A-Za-z0-9]{16,})\b')
ACCEPT_LOOSE_KEY = False      # принимать «похоже на ключ» без шаблона (в v18.8 выключено)

PACKAGE_MAIN = "com.roblox.client"
PLACE_ID = "142823291"

# --- системные пути (~/farm) ---
FARM_BASE = Path(__file__).resolve().parents[2]      # services/farm/main.py -> ~/farm
STATE_FILE = FARM_BASE / "info" / "farm_state.json"  # состояние переживает всё
EVENTS_FILE = FARM_BASE / "info" / "farm_events.jsonl"  # события фарма (этап 2)
EVENTS_MAX_BYTES = 512 * 1024   # ротация: файл разросся → оставляем хвост
EVENTS_KEEP = 300               # сколько последних событий переживает ротацию
# 🌾 окно сбора урожая: пишет КЛИЕНТ (задача harvest.start с сервера), фарм ТОЛЬКО читает
HARVEST_WINDOW_FILE = FARM_BASE / "info" / "harvest_window.json"
# 🔓 флаг байпаса по кнопке: пишет КЛИЕНТ (задача bypass.run с сервера/дашборда),
# фарм забирает его и делает ПОЛНЫЙ цикл v18.8 (Delta → ZEN-API → ключ → license)
BYPASS_FORCE_FILE = FARM_BASE / "info" / "bypass_force.json"
BYPASS_FLAG_TTL = 12 * 3600   # 🆕 v0.18: кнопка «живёт» 12ч — застрявший флаг не гоняет байпас вечно
BYPASS_MIN_KEY_AGE_H = 23.0   # 🔓 v0.26 ПРАВИЛО ХОЗЯИНА: байпас только если ключу ≥23ч

state = {"last_key_time": 0.0}


def key_age_h() -> float | None:
    """🔓 v0.26: возраст ключа Дельты (часы) или None — ключа не было/неизвестно.
    None = байпас ДОЛЖЕН пройти (фарм без ключа не работает)."""
    try:
        kt = float(state.get("last_key_time") or 0)
    except Exception:
        return None
    if kt <= 0:
        return None
    return (time.time() - kt) / 3600


def bypass_key_old_enough() -> tuple[bool, float | None]:
    """🔓 v0.26: (True, age) — байпас можно делать (ключа нет ИЛИ ключу ≥23ч).
    (False, age) — ключ СВЕЖИЙ (<23ч): байпас вхолостую не гоняем.
    force:true во флаге обходит это правило (явное желание владельца)."""
    age = key_age_h()
    if age is None or age >= BYPASS_MIN_KEY_AGE_H:
        return True, age
    return False, age

# 🌾 v0.20 СБОР-ТРЕЙД: скрипты хозяина на GitHub (raw)
HARVEST_TREID_URL = "https://raw.githubusercontent.com/gleb228666999/test/refs/heads/main/treid.lua"
HARVEST_IDS_URL = "https://raw.githubusercontent.com/gleb228666999/test/refs/heads/main/id.txt"
TREID_CACHE_FILE = FARM_BASE / "info" / "harvest_treid.lua"   # кэш на случай, если GitHub недоступен
IDS_CACHE_FILE = FARM_BASE / "info" / "harvest_ids.txt"       # (общий кэш с сервисом collector)
# 🔥 v0.22: ЗАШИТЫЕ КОДЫ ПРИВАТОК — локальный фолбэк, КАК В РАБОЧЕМ СКРИПТЕ
# хозяина (collet(1).py, PRIVATE_SHARE_CODES): если id.txt недоступен с телефона
# (сеть/GitHub) и кэша нет — фермеры ВСЁ РАВНО заходят в приватки по этим кодам,
# а НЕ уходят в обычный плейс. Список синхронизирован с id.txt хозяина.
PRIVATE_SHARE_CODES_FALLBACK = [
    "56c0dba8b10a4d44a9cd5c9b2b41265f",
    "c9201bc54ffbc343a7175a1385c0f4ce",
    "f7e4f4a2b71ded49a4aab247eec9c62f",
    "2ce541838492ac41b0bd0be49a8d995c",
]
HARVEST_RELAUNCH_GRACE = 90   # сек после запуска в приватку, прежде чем считать клон вылетевшим
                              # (share-ссылка идёт через браузер — редирект занимает время)
# 🛡 v0.20 kill-switch регы акков: пишет КЛИЕНТ (rega.switch с сервера)
REGA_SWITCH_FILE = FARM_BASE / "info" / "rega_switch.json"
_last_blocked_emit = [0.0]   # 🛡 v0.23: троттлинг rega.blocked (не спамить 60 раз в час)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================================
# 🛠 su (PATH может быть побит root-стражем)
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
        res = subprocess.run([SU_BIN, "-c", cmd], capture_output=True,
                             text=True, timeout=timeout, errors="replace")
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as e:
        return False, "", str(e)


def tap(x, y, delay=0, name=""):
    if name:
        log(f"👆 {name} ({x}, {y})")
    run_su(f"input tap {x} {y}", timeout=5)
    if delay:
        time.sleep(delay)


def set_landscape():
    run_su("settings put system accelerometer_rotation 0", timeout=5)
    run_su("settings put system user_rotation 1", timeout=5)


def set_portrait():
    run_su("settings put system user_rotation 0", timeout=5)
    run_su("settings put system accelerometer_rotation 1", timeout=5)


def _current_rotation():
    """0/2 = портрет, 1/3 = ландшафт. Читаем реальный поворот (dumpsys input, фолбэк dumpsys window)."""
    ok, out, _ = run_su(
        "dumpsys input | grep -i 'SurfaceOrientation' || dumpsys window | grep 'mRotation='",
        timeout=5)
    if not ok:
        return ""
    vals = re.findall(r'(?:SurfaceOrientation|mRotation)\s*[:=]\s*([0-9])', out)
    return vals[-1] if vals else ""


def force_landscape(reason="", verify=True):
    """📱 v0.16: ОРИЕНТАЦИЯ ВСЕГДА ГОРИЗОНТАЛЬНАЯ.
    Все координаты байпаса (Дельта + браузер) — ЛАНДШАФТНЫЕ. Chrome и система
    сбрасывают поворот при переходе на сайт get key → клики промахиваются.
    Выставляем user_rotation=1 + блокируем акселерометр и ПРОВЕРЯЕМ реальный
    поворот по dumpsys; не повернулся — повторяем (до 3 раз).
    🆕 v0.18: verify=False — быстрая версия (только 2 settings-команды, без
    dumpsys и повторов) для путей с жёстким бюджетом времени (graceful_stop ≤25с:
    полная проверка в худшем случае ≈50с → фарм убили бы SIGKILL посреди зачистки)."""
    if reason:
        log(f"📱 {reason} → форсирую ЛАНДШАФТ")
    if not verify:
        run_su("settings put system accelerometer_rotation 0", timeout=3)
        run_su("settings put system user_rotation 1", timeout=3)
        return True
    for attempt in (1, 2, 3):
        run_su("settings put system accelerometer_rotation 0", timeout=5)
        run_su("settings put system user_rotation 1", timeout=5)
        time.sleep(1.2)  # системе нужно время реально повернуть экран
        orient = _current_rotation()
        if orient in ("1", "3"):
            if reason:
                log(f"   ✅ Ландшафт подтверждён (orient={orient})")
            return True
        if attempt < 3:
            log(f"   ⚠️ Поворот не применился (orient={orient or '?'}) — повтор {attempt + 1}/3")
    log("   ⚠️ Ландшафт не подтвердился dumpsys, но настройки выставлены — продолжаю")
    return False


def wake_screen():
    ok, out, _ = run_su("dumpsys power | grep 'mWakefulness='", timeout=5)
    if ok and "mWakefulness=Awake" in out:
        return
    log("🌅 Экран выключен — буджу")
    run_su("input keyevent 224", timeout=5)
    time.sleep(1)
    run_su("input keyevent 82", timeout=5)
    time.sleep(1)


def select_all_delete():
    run_su("input keycombination 113 29", timeout=5)
    time.sleep(0.3)
    run_su("input keyevent 67", timeout=5)
    time.sleep(0.3)


# ==========================================
# 📄 UI DUMP (uiautomator, кэш 1с — как в v18.8)
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


def get_visible_text():
    xml = ui_dump()
    if not xml:
        return []
    texts = []
    for attr in ("text", "content-desc"):
        for raw in re.findall(rf'{attr}="([^"]+)"', xml):
            t = html.unescape(raw).strip()
            if t:
                texts.append(t)
    return texts


# ==========================================
# 💾 СОСТОЯНИЕ (info/farm_state.json, атомарно)
# ==========================================

def load_state():
    global state
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text())
            state.update(loaded)
            log(f"📂 State загружен: last_key_time={state.get('last_key_time')}")
        except Exception as e:
            log(f"⚠️ State битый ({e}), начинаю с нуля")
            state = {"last_key_time": 0.0}


def save_state():
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE_FILE)          # атомарно, переживает всё
    except Exception as e:
        log(f"⚠️ save_state: {e}")


def graceful_stop(reason: str):
    """Единый выход (v0.13 — ПОЛНЫЙ стоп): state → глушим регу → зачистка
    роблоксов → контрольный добой рега → событие farm.stop.
    Бюджет: рега ≤8с + роблоксы ≤15с = ≤23с — влезает в PM.stop timeout 25с."""
    save_state()
    rega_stopped = False
    try:
        rega_stopped = stop_rega()
    except Exception as e:
        log(f"⚠️ стоп рега: {e}")
    try:
        closed = shutdown_kill_roblox()
    except Exception as e:
        log(f"⚠️ зачистка роблоксов: {e}")
        closed = -1
    try:
        force_landscape("Стоп фарма", verify=False)   # v0.16+18: ландшафт, БЕЗ dumpsys — бюджет 25с
    except Exception:
        pass
    try:
        # контрольный добой: если рега пережила SIGTERM — SIGKILL (без ожидания)
        if _rega_pid():
            run_su("pkill -9 -f 'services/rega/main[.]py'", timeout=5)
            rega_stopped = True
    except Exception:
        pass
    emit("farm.stop", closed=closed, reason=reason, rega_stopped=rega_stopped)


def _sigterm(signum, frame):
    """Корректная остановка: farm ⏹ / полный стоп / рестарт сервиса.
    При остановке закрываем все роблоксы — телефон остаётся чистым."""
    log("🛑 SIGTERM: сохраняю state, закрываю роблоксы, выхожу...")
    graceful_stop("sigterm")
    sys.exit(0)


# ==========================================
# 📤 СОБЫТИЯ (info/farm_events.jsonl, этап 2)
# ==========================================
# Фарм только ПИШЕТ события. Кто их заберёт (клиент → сервер → SQLite) —
# фарм не волнует. Дубликаты не страшны: сервер отсекает по id.

def emit(etype, **info):
    """Одна JSON-строка в farm_events.jsonl. Никогда не роняет фарм."""
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # примитивная ротация: разросся → оставляем хвост
        try:
            if EVENTS_FILE.exists() and EVENTS_FILE.stat().st_size > EVENTS_MAX_BYTES:
                tail = EVENTS_FILE.read_text().splitlines()[-EVENTS_KEEP:]
                tmp = EVENTS_FILE.with_suffix(".tmp")
                tmp.write_text("\n".join(tail) + "\n")
                tmp.replace(EVENTS_FILE)
        except Exception:
            pass
        ev = {
            "id": f"{int(time.time()*1000):x}-{os.urandom(3).hex()}",
            "ts": round(time.time(), 2),
            "type": etype,
            "info": info,
        }
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"⚠️ emit({etype}): {e}")


# ==========================================
# 🌾 СБОР УРОЖАЯ (окно пишет клиент, фарм читает)
# ==========================================
# Сервер шлёт harvest.start → клиент пишет info/harvest_window.json
# {until_ts, place_id, hold}. Фарм в цикле/мониторинге видит окно → входит в
# приватки: v0.24 HOLD — БЕССРОЧНО (до кнопки «НОВЫЙ ЦИКЛ» на панели, сервер
# пришлёт harvest.stop). harvest.stop → клиент удаляет файл.

def harvest_window():
    """Активное окно сбора или None (нет/истекло/снято).
    🆕 v0.24: hold=True — окно БЕЗ СРОКА (HOLD): сидим в приватках с treid.lua,
    пока сервер не пришлёт harvest.stop (кнопка «НОВЫЙ ЦИКЛ»)."""
    try:
        hw = json.loads(HARVEST_WINDOW_FILE.read_text())
        until = float(hw.get("until_ts") or 0)
        if time.time() >= until:
            return None
        return {"until_ts": until, "place_id": str(hw.get("place_id") or ""),
                "hold": bool(hw.get("hold"))}
    except Exception:
        return None


def bypass_requested() -> bool:
    """🔓 Кнопка байпаса на дашборде (клиент пишет bypass_force.json)?
    🆕 v0.18: протухший (>12ч) флаг удаляем и игнорируем — не вечный цикл."""
    try:
        if not BYPASS_FORCE_FILE.is_file():
            return False
        data = json.loads(BYPASS_FORCE_FILE.read_text())
        ts = float(data.get("ts") or 0) if isinstance(data, dict) else 0
    except Exception:
        return True   # прочитать не вышло — пусть consume разберётся
    if ts and time.time() - ts > BYPASS_FLAG_TTL:
        log(f"🗑 Флаг байпаса протух (>{BYPASS_FLAG_TTL // 3600}ч) — удаляю, не выполняю")
        try:
            BYPASS_FORCE_FILE.unlink()
        except Exception:
            pass
        return False
    return True


def consume_bypass_request():
    """Забрать флаг байпаса (атомарно: прочитали → удалили). None = флага нет.
    🆕 v0.18: если удалить не удалось — вернём None. Раньше возвращали «флаг
    забран», хотя файл оставался на диске → байпас запускался заново каждый
    проход цикла (вечный круг без остановки)."""
    try:
        data = json.loads(BYPASS_FORCE_FILE.read_text())
    except Exception:
        data = {"ts": round(time.time(), 1)}
    try:
        BYPASS_FORCE_FILE.unlink()
    except FileNotFoundError:
        return None
    except Exception as e:
        log(f"⚠️ Флаг байпаса не удаётся удалить ({e}) — НЕ запускаю (иначе вечный цикл)")
        return None
    ts = float(data.get("ts") or 0) if isinstance(data, dict) else 0
    if ts and time.time() - ts > BYPASS_FLAG_TTL:
        log(f"🗑 Флаг байпаса протух (>{BYPASS_FLAG_TTL // 3600}ч) — не выполняю")
        return None
    return data


# ==========================================
# 📝 DELTA LUA
# ==========================================

def create_delta_lua(content=None):
    """🔥 ВСЕГДА перезаписывает Delta Lua файл при каждом запуске.
    🆕 v0.20: content=None → фарм-скрипт (DELTA_LUA_CONTENT); при СБОРЕ сюда
    пишется treid.lua, после окна вызываем без аргумента — возвращаем фарм."""
    lua = content if content is not None else DELTA_LUA_CONTENT
    label = "treid.lua (СБОР)" if content is not None else "фарм-скрипт"
    log(f"📝 ПЕРЕЗАПИСЫВАЮ Delta Lua: {DELTA_AUTOEXEC_PATH} ({label})")
    log(f"   📄 Начало: {lua[:60]}")

    try:
        folder = os.path.dirname(DELTA_AUTOEXEC_PATH)
        if not os.path.exists(folder):
            run_su(f"mkdir -p '{folder}'", timeout=5)
            log(f"   📁 Создана папка: {folder}")

        with open(DELTA_AUTOEXEC_PATH, 'w') as f:
            f.write(lua)

        run_su(f"chmod 644 '{DELTA_AUTOEXEC_PATH}'", timeout=3)

        try:
            with open(DELTA_AUTOEXEC_PATH, 'r') as f:
                content_read = f.read().strip()
            if content_read == lua.strip():
                log("✅ Delta Lua перезаписан УСПЕШНО")
            else:
                log(f"⚠️ Содержимое отличается! Записано: {content_read[:50]}")
        except Exception as e:
            log(f"⚠️ Не удалось проверить содержимое: {e}")

        return True
    except Exception as e:
        log(f"❌ Ошибка перезаписи Lua: {e}")

        log("🔄 Пробую через su...")
        try:
            escaped_content = lua.replace("'", "'\"'\"'")
            ok, out, err = run_su(f"echo '{escaped_content}' > '{DELTA_AUTOEXEC_PATH}'", timeout=5)
            if ok:
                run_su(f"chmod 644 '{DELTA_AUTOEXEC_PATH}'", timeout=3)
                log("✅ Delta Lua перезаписан через su")
                return True
            else:
                log(f"❌ su тоже не сработал: {err}")
        except Exception as e2:
            log(f"❌ Фоллбэк провалился: {e2}")

        return False


# ==========================================
# 📱 УПРАВЛЕНИЕ ПАКЕТАМИ
# ==========================================

def _list_roblox_packages():
    """Все пакеты com.roblox* (основной + клоны)"""
    ok, out, _ = run_su("pm list packages com.roblox", timeout=10)
    if not ok:
        return []
    return [line.split(":")[1] for line in out.splitlines() if line.startswith("package:")]


def kill_all_roblox():
    log("🛑 Убиваю ВСЕ процессы Roblox...")
    pkgs = _list_roblox_packages()
    for pkg in pkgs:
        run_su(f"am force-stop {pkg}", timeout=5)
    run_su("am force-stop com.android.chrome", timeout=5)
    run_su("am force-stop com.android.browser", timeout=5)
    log(f"   ✅ Остановлено: {len(pkgs)} пакетов")
    time.sleep(2)


def shutdown_kill_roblox(deadline_s=15):
    """🧹 Остановка фарма = чистый телефон: закрываем ВСЕ роблоксы и браузеры
    (браузер фарм сам открывает при байпасе). Быстрая версия без паузы в конце:
    ProcessManager даёт ~25с до SIGKILL — дедлайн держим 15с."""
    log("🧹 Остановка фарма: закрываю все роблоксы...")
    closed = 0
    deadline = time.time() + deadline_s
    for pkg in _list_roblox_packages():
        if time.time() >= deadline:
            log("⏰ Дедлайн зачистки — выхожу как есть")
            break
        run_su(f"am force-stop {pkg}", timeout=5)
        closed += 1
    if time.time() < deadline:
        run_su("am force-stop com.android.chrome", timeout=5)
        run_su("am force-stop com.android.browser", timeout=5)
    log(f"   ✅ Закрыто роблоксов: {closed}")
    return closed


def launch_delta():
    log(f"🔓 Запускаю Дельту (com.roblox.client) СРАЗУ в плейс {PLACE_ID} для байпаса...")
    deep_link = f"'roblox://experiences/start?placeId={PLACE_ID}'"
    run_su(f"am start -a android.intent.action.VIEW -d {deep_link} {PACKAGE_MAIN}", timeout=10)


def get_farm_packages():
    """Возвращает список пакетов-клонов для фарма (кроме основного), максимум 4"""
    farm_pkgs = [pkg for pkg in _list_roblox_packages() if pkg != PACKAGE_MAIN]
    return farm_pkgs[:4]


def launch_roblox_light_farm(place=None):
    log("🚜 Запускаю ферму (Ожидание 15 сек -> Прямой запуск в плейс)...")
    place = place or PLACE_ID
    farm_pkgs = get_farm_packages()
    if not farm_pkgs:
        log("⚠️ Нет пакетов для фарма")
        return []

    launched = 0
    for pkg in farm_pkgs:
        log(f"⏳ Ожидание {FARM_PRELAUNCH_DELAY} секунд перед запуском {pkg}...")
        time.sleep(FARM_PRELAUNCH_DELAY)

        deep_link = f"'roblox://experiences/start?placeId={place}'"
        log(f"🚀 Прямой запуск в плейс {place} для {pkg}...")
        run_su(f"am start -a android.intent.action.VIEW -d {deep_link} {pkg}", timeout=5)

        launched += 1
        time.sleep(2)

    log(f"   ✅ Фермеров запущено: {launched}")
    return farm_pkgs


# ==========================================
# ⬇ СКАЧИВАНИЕ СКРИПТОВ СБОРА (с кэш-фоллбэком)
# ==========================================

def fetch_text(url, cache_path, timeout=25):
    """⬇ Текст по HTTP с кэш-фоллбэком: скачали → сохранили в кэш;
    сеть упала → отдаём кэш; и то и другое не вышло → None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FarmBot/16.6"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
        if text and text.strip():
            try:
                tmp = Path(str(cache_path) + ".tmp")
                tmp.write_text(text)
                tmp.replace(cache_path)      # атомарно
            except Exception:
                pass
            return text
    except Exception as e:
        log(f"⬇ {str(url).rsplit('/', 1)[-1]}: сеть не удалась ({e})")
    try:
        if Path(cache_path).exists():
            text = Path(cache_path).read_text(errors="replace")
            if text.strip():
                log(f"📂 Использую кэш: {Path(cache_path).name}")
                return text
    except Exception:
        pass
    return None


def parse_share_codes(text):
    """Из id.txt достаём 32-символьные hex share-коды приваток
    (устойчиво к пробелам, переводам строк и посторонним пояснениям)."""
    seen, out = set(), []
    for m in re.findall(r'\b[0-9a-fA-F]{32}\b', text or ""):
        c = m.lower()
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def private_deep_link(code, place=None):
    """🔥 v0.21: ПРЯМОЙ deep link В ПРИВАТКУ (как в рабочем скрипте хозяина
    collet(1).py): placeId + privateServerLinkCode — Roblox заходит на
    приватный сервер НАПРЯМУЮ, без браузерного редиректа."""
    return f"roblox://experiences/start?placeId={place or PLACE_ID}&privateServerLinkCode={code}"


def am_start_link(link, pkg, place=None):
    """🚀 v0.21: запуск pkg по ссылке — ЕДИНЫЙ АЛГОРИТМ ЗАХОДА, КАК В РАБОЧЕМ
    СКРИПТЕ ХОЗЯИНА (collet(1).py):
      1) share-ссылка 'https://www.roblox.com/share?code=...&type=Server'
         (браузер → редирект в Roblox);
      2) am start не сработал → ПРЯМОЙ deep link В ПРИВАТКУ
         (placeId + privateServerLinkCode из share-кода) — раньше фолбэк вёл
         в обычный плейс БЕЗ кода привата, и фермеры не заходили в приватки.
    Возвращает True, если сработал первый метод (share)."""
    ok, _, _ = run_su(f"am start -a android.intent.action.VIEW -d '{link}' {pkg}", timeout=5)
    if ok:
        return True
    m = re.search(r'code=([0-9a-fA-F]{32})', link or "")
    if m:
        code = m.group(1)
        log(f"   ⚠️ Метод 1 (Share) не сработал для {pkg} — фолбэк: deep link в приватку {code[:8]}…")
        run_su(f"am start -a android.intent.action.VIEW -d '{private_deep_link(code, place)}' {pkg}", timeout=5)
    else:
        log(f"   ⚠️ am start не сработал для {pkg} — фолбэк: deep link в плейс {place or PLACE_ID}")
        run_su(f"am start -a android.intent.action.VIEW -d 'roblox://experiences/start?placeId={place or PLACE_ID}' {pkg}", timeout=5)
    return False


def launch_farmers_private(codes):
    """🚜 v0.21: запуск клонов НА ПРИВАТНЫЕ СЕРВЕРА — алгоритм ИЗ РАБОЧЕГО
    скрипта хозяина (collet(1).py): share-ссылка → если не сработала, фолбэк —
    прямой deep link В ПРИВАТКУ (placeId + privateServerLinkCode), а НЕ в
    обычный плейс. Коды расходятся по клонам ПО КРУГУ.
    Возвращает (пакеты, {pkg: share-ссылка для перезапуска})."""
    farm_pkgs = get_farm_packages()
    launch_map = {}
    if not farm_pkgs:
        log("⚠️ Нет пакетов для фарма")
        return [], {}
    launched = 0
    for i, pkg in enumerate(farm_pkgs):
        code = codes[i % len(codes)]
        share = f"https://www.roblox.com/share?code={code}&type=Server"
        launch_map[pkg] = share
        log(f"🔗 [{i + 1}] {pkg} → приватка {code[:8]}…")
        am_start_link(share, pkg)
        launched += 1
        time.sleep(2)
    log(f"   ✅ Фермеров запущено в приватки: {launched}")
    log("   ⏳ Жду 5 сек на обработку share-ссылок браузером...")
    time.sleep(5)
    return farm_pkgs, launch_map


# ==========================================
# 🔍 МОНИТОРИНГ ВИДИМОСТИ ОКОН
# ==========================================

def get_visibility_snapshots():
    """Получает дампы окон и activity для проверки видимости пакетов"""
    ok1, win_out, _ = run_su("dumpsys window windows", timeout=10)
    ok2, act_out, _ = run_su("dumpsys activity activities", timeout=10)

    if not ok1 and not ok2:
        return None, None

    return win_out or "", act_out or ""


def is_pkg_visible(pkg, win_out, act_out):
    """
    🔍 Проверяет, видно ли окно пакета.
    Учитывает плавающие окна / freeform / foreground.
    Если окно не найдено — пакет считается невидимым.
    """
    # Если вообще нет данных, считаем видимым, чтобы не устроить массовый перезапуск
    if not win_out and not act_out:
        return True

    # 1) Проверка через окна
    if win_out:
        # Разбиваем на блоки Window #..., сохраняя заголовок
        blocks = re.split(r'(?=Window #\d+)', win_out)
        for block in blocks:
            if f"mPackageName={pkg}" not in block and f"{pkg}/" not in block:
                continue

            # Явный признак видимого окна
            if re.search(r'isReadyForDisplay=true', block, re.I):
                return True

            # mViewVisibility=0x0 означает View.VISIBLE
            view_visible = re.search(r'mViewVisibility=0x0', block)
            has_surface = re.search(r'mHasSurface=true', block, re.I)
            drawn = re.search(r'mDrawState=(HAS_DRAWN|COMMIT_DRAW_PENDING|DRAW_PENDING)', block, re.I)

            if view_visible and (has_surface or drawn):
                return True

            # Некоторые прошивки используют mIsVisible
            if re.search(r'mIsVisible=true', block, re.I):
                return True

    # 2) Проверка через activity
    if act_out:
        # Если пакет является focused / resumed / top
        if re.search(
            rf'(mResumedActivity|mFocusedActivity|topResumedActivity|mLastResumedActivity).*{re.escape(pkg)}',
            act_out
        ):
            return True

        # Проверяем ActivityRecord блоки
        blocks = re.split(r'(?=ActivityRecord\{)', act_out)
        for block in blocks:
            if pkg not in block:
                continue

            if re.search(r'visible=true', block, re.I):
                return True

            # В multi-window / freeform activity может быть RESUMED
            if re.search(r'state=RESUMED', block, re.I):
                return True

        # Проверяем Task блоки (freeform stack)
        blocks = re.split(r'(?=Task\{)', act_out)
        for block in blocks:
            if pkg in block and re.search(r'visible=true', block, re.I):
                return True

    return False


def restart_pkg(pkg, place=None, link=None):
    """🔄 Принудительно останавливает пакет, ждет 15 сек и запускает его снова.
    🆕 v0.21: link — share-ссылка приватки (сбор): клон возвращается НА СВОЙ
    приватный сервер; если share не сработала — фолбэк КАК В СКРИПТЕ ХОЗЯИНА:
    прямой deep link в приватку (placeId + privateServerLinkCode из share-кода).
    link="" или None — как раньше, deep link в плейс."""
    place = place or PLACE_ID
    emit("farm.restart", pkg=pkg, private=bool(link))
    log(f"⚠️ Окно {pkg} не видно → останавливаю пакет...")
    run_su(f"am force-stop {pkg}", timeout=5)

    log(f"⏳ Ожидание {FARM_RESTART_DELAY} секунд перед перезапуском {pkg}...")
    time.sleep(FARM_RESTART_DELAY)

    if link:
        log(f"🚀 Повторный запуск {pkg} НА ПРИВАТНЫЙ СЕРВЕР...")
        am_start_link(link, pkg, place)
        return
    deep_link = f"'roblox://experiences/start?placeId={place}'"
    log(f"🚀 Повторный запуск {pkg} в плейс {place}...")
    run_su(f"am start -a android.intent.action.VIEW -d {deep_link} {pkg}", timeout=5)


def monitor_farm(duration, farm_pkgs, harvest=False, launch_map=None):
    """👁 Мониторинг фермы: каждые FARM_CHECK_INTERVAL секунд проверяет видимость окон.
    Одна компактная строка на проверку (ротации логов нет) + отдельные строки на перезапуски.
    harvest=True — это мониторинг СБОРА: выходим, когда окно сбора исчезло.
    harvest=False — обычный фарм: выходим, когда окно сбора ПОЯВИЛОСЬ (20:00 МСК).
    🆕 v0.20: launch_map — {pkg: share-ссылка приватки}: вылетевший клон возвращается
    НА СВОЙ приватный сервер; на долёт через браузерный редирект даём grace
    HARVEST_RELAUNCH_GRACE сек (иначе зациклим перезапуски на этапе редиректа)."""
    launch_map = launch_map or {}
    last_launch = {p: time.time() for p in launch_map}   # grace при старте сессии
    if not farm_pkgs:
        log("⚠️ Нет пакетов для мониторинга, просто ждём...")
        # даже без пакетов ждём с проверкой окна сбора И флага байпаса
        end0 = time.time() + duration
        while time.time() < end0:
            if bypass_requested():
                log("🔓 Запрошен байпас с дашборда — выхожу из ожидания")
                return "bypass"
            if (harvest_window() is not None) != harvest:
                return None
            time.sleep(min(FARM_CHECK_INTERVAL, max(0, end0 - time.time())))
        return None

    log(f"👁 Мониторинг {len(farm_pkgs)} пакетов каждые {FARM_CHECK_INTERVAL} сек...")
    log(f"⏱️ Задержка перед перезапуском вылетевшего: {FARM_RESTART_DELAY} сек")

    end_time = time.time() + duration

    while time.time() < end_time:
        sleep_time = min(FARM_CHECK_INTERVAL, max(0, end_time - time.time()))
        if sleep_time > 0:
            time.sleep(sleep_time)

        if time.time() >= end_time:
            break

        # 🔓 байпас по кнопке — приоритетнее всего (фарм и сбор прерываем)
        if bypass_requested():
            log("🔓 Запрошен байпас с дашборда — прерываю мониторинг")
            return "bypass"

        # 🌾 окно сбора появилось (обычный фарм) или исчезло (сбор) → выходим,
        # вызывающий код сам переключится на сбор / вернётся к фарму
        if (harvest_window() is not None) != harvest:
            log("🌾 Изменение окна сбора — переключаю режим")
            return None

        log("🔍 Проверка видимости окон фермы...")
        win_out, act_out = get_visibility_snapshots()

        if win_out is None and act_out is None:
            log("⚠️ Не удалось получить dumpsys, пропускаю проверку")
            continue

        statuses = []
        for pkg in farm_pkgs:
            if not is_pkg_visible(pkg, win_out, act_out):
                # 🆕 v0.20: grace после запуска в приватку — ждём долёт (браузер → Roblox)
                if pkg in launch_map and time.time() - last_launch.get(pkg, 0) < HARVEST_RELAUNCH_GRACE:
                    statuses.append(f"{pkg.split('.')[-1]}⏳")
                    continue
                log(f"⚠️ {pkg} НЕ виден → перезапуск через {FARM_RESTART_DELAY} сек")
                restart_pkg(pkg, link=launch_map.get(pkg) or None)
                last_launch[pkg] = time.time()
                time.sleep(2)
                statuses.append(f"{pkg.split('.')[-1]}♻️")
            else:
                statuses.append(f"{pkg.split('.')[-1]}✅")

        remaining = max(0, end_time - time.time())
        log(f"👁 до конца {remaining/60:.0f} мин: " + " ".join(statuses))


def run_harvest_session(hw):
    """🌾 СБОР УРОЖАЯ v2 — БЕЗОПАСНЫЙ ТРЕЙД (v0.20, по скриптам хозяина):
    • treid.lua (GitHub, кэш) на время окна становится автоэкзекютом Дельты —
      клоны масс-трейдят ВЕСЬ лут целевым аккам-сборщикам;
    • приватки ТОЛЬКО из id.txt хозяина (share-коды, кэш); клоны по кругу;
    • вылетевший клон возвращается НА СВОЙ приватный сервер;
    • после окна (ЛЮБОЙ исход) — kill + восстановление фарм-автоэкзекюта.
    🛡 АККИ НЕ ТРОГАЕМ: ни куки, ни WebView — только трейд предметов. Цели
    офлайн → treid.lua сам ждёт, лут остаётся у фармера. treid.lua недоступен
    (сеть + кэш) → сбор на этом телефоне отменяется (не гоняем фарм-скрипт
    в приватки впустую)."""
    until = float(hw.get("until_ts") or 0)
    place = hw.get("place_id") or PLACE_ID
    hold = bool(hw.get("hold"))                # 🆕 v0.24: HOLD — бессрочно, до «НОВЫЙ ЦИКЛ»
    minutes = max(1, int((until - time.time()) // 60))

    treid = fetch_text(HARVEST_TREID_URL, TREID_CACHE_FILE)
    if not treid:
        log("🛡 treid.lua недоступен (нет сети и кэша) — СБОР ОТМЕНЁН на этом телефоне")
        emit("harvest.skip", reason="treid.lua недоступен")
        return None

    codes = parse_share_codes(fetch_text(HARVEST_IDS_URL, IDS_CACHE_FILE) or "")
    if codes:
        log(f"🔗 Приватные сервера из id.txt: {len(codes)} шт.")
    else:
        # 🔥 v0.22: КАК В РАБОЧЕМ СКРИПТЕ хозяина — зашитые коды привяток.
        # Раньше фолбэком был ОБЫЧНЫЙ ПЛЕЙС — фермеры уходили в публичку и
        # сбор не работал. Теперь привятки есть ВСЕГДА.
        codes = list(PRIVATE_SHARE_CODES_FALLBACK)
        log(f"⚠️ id.txt недоступен — зашитый фолбэк привяток (как в рабочем скрипте): {len(codes)} шт.")

    # 🍪 без кук на клонах в приватки не зайти — не стартуем (куки НЕ трогаем!)
    farm_pkgs_all = get_farm_packages()
    with_sess = sum(1 for p in farm_pkgs_all if has_session(p))
    if farm_pkgs_all and with_sess == 0:
        log("🛡 У клонов нет живых кук — в приватки не зайти, сбор не запускаю")
        emit("harvest.skip", reason="нет кук на клонах")
        return None

    log(f"🌾 СБОР УРОЖАЯ (трейд): {'HOLD — до кнопки «НОВЫЙ ЦИКЛ» (бессрочно)' if hold else f'{minutes} мин'}"
        f" · кук у клонов {with_sess}/{len(farm_pkgs_all)} "
        f"· приваток {len(codes) or 'нет (плейс)'}")
    emit("harvest.start", minutes=(0 if hold else minutes), hold=hold, place=place,
         codes=len(codes), clones=len(farm_pkgs_all))

    # 📝 автоэкзекют → treid.lua (после окна вернём фарм-скрипт в finally)
    create_delta_lua(treid)

    res = None
    try:
        kill_all_roblox()
        if codes:
            farm_pkgs, launch_map = launch_farmers_private(codes)
        else:
            farm_pkgs = launch_roblox_light_farm(place=place)
            launch_map = {}
        res = monitor_farm(max(60, until - time.time()), farm_pkgs,
                           harvest=True, launch_map=launch_map)
    finally:
        # 🧹 любой исход: чистим роблоксы и ВОЗВРАЩАЕМ ФАРМ-СКРИПТ
        try:
            kill_all_roblox()
        finally:
            create_delta_lua()   # фарм 1.lua — дальше обычный фарм
            log("🔁 Автоэкзекют возвращён к фарм-скрипту")

    if res == "bypass":
        # 🆕 v0.18: возвращаем "bypass" — main() СЕЙЧАС съест флаг и сделает байпас,
        # потом сбор продолжится на остаток окна (окно ещё активно).
        emit("harvest.end", reason="bypass_requested",
             hold=hold, minutes_left=(0 if hold else max(0, int((until - time.time()) // 60))))
        log("🌾 Сбор прерван байпасом с дашборда — сейчас байпас, потом сбор продолжится")
        return "bypass"
    emit("harvest.end", hold=hold)
    log("🌾 Сбор завершён — закрываю роблоксы, возвращаюсь к фарму")


# ==========================================
# 🍪 КУКИ-ГЕЙТ (v0.12): нет кук у Дельты или у клонов → сначала рега
# ==========================================
# Байпасу нужна залогиненная Дельта, фермерам — залогиненные клоны.
# v0.11 считал только «0 сессий вообще» — кука Дельты маскировала пустые
# клоны и фарм гонял байпас/фарм впустую. Теперь гейт проверяет ОБЕ части:
#   • куки Дельты нет        → байпас не работает → рега;
#   • ВСЕ клоны без сессий   → фармить нечем → рега.
# Частичная убыль кук регу НЕ поднимает (починка: check → пул/архив,
# ежедневная рега в 03:00) — иначе сломанный клон гонял бы регу по кругу.

TERMUX_HOME = os.environ.get("HOME", "/data/data/com.termux/files/home")
CHECK_DB = os.path.join(TERMUX_HOME, "Cookies_check.db")   # СВОЙ рабочий файл (не как у рега!)
REGA_SCRIPT = FARM_BASE / "services" / "rega" / "main.py"
REGA_LOCK = FARM_BASE / "info" / "rega.lock"     # тот же лок, что у рега-сервиса
REGA_WAIT_MAX = 4 * 3600        # сколько ждём окончания рега
REGA_RETRY_PAUSE = 30 * 60      # рега не дала кук → пауза перед новой попыткой


def _cookie_db_candidates(pkg):
    base = f"/data/data/{pkg}/app_webview"
    return [f"{base}/Default/Cookies",
            f"{base}/Default/Network/Cookies",
            f"{base}/Cookies"]


def _copy_check_db(db):
    run_su(f"rm -f '{CHECK_DB}' '{CHECK_DB}-wal' '{CHECK_DB}-journal' '{CHECK_DB}-shm'")
    run_su(f"cp '{db}' '{CHECK_DB}' 2>/dev/null")
    run_su(f"cp '{db}-wal' '{CHECK_DB}-wal' 2>/dev/null")
    run_su(f"cp '{db}-shm' '{CHECK_DB}-shm' 2>/dev/null")
    run_su(f"chmod 666 '{CHECK_DB}' '{CHECK_DB}-wal' '{CHECK_DB}-shm' 2>/dev/null")


def _clean_check_db():
    run_su(f"rm -f '{CHECK_DB}' '{CHECK_DB}-wal' '{CHECK_DB}-journal' '{CHECK_DB}-shm'")


def has_session(pkg):
    """Есть ли в WebView DB пакета живая .ROBLOSECURITY (кука)."""
    for db in _cookie_db_candidates(pkg):
        if not run_su(f"test -f '{db}'")[0]:
            continue
        _copy_check_db(db)
        con = None
        try:
            con = sqlite3.connect(CHECK_DB)
            has = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name='cookies'").fetchone()
            if not has:
                continue
            rows = con.execute("SELECT length(value) FROM cookies "
                               "WHERE name='.ROBLOSECURITY'").fetchall()
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
            _clean_check_db()
    return False


def total_sessions():
    """Сколько пакетов залогинено (клоны + main)."""
    n = sum(1 for pkg in get_farm_packages() if has_session(pkg))
    if has_session(PACKAGE_MAIN):
        n += 1
    return n


def _roblox_auth_check(cookie):
    """API Roblox: жива ли кука. "ok"/"dead"(401)/"error"(сеть и пр.) — порт fetch_user_info_full из рега."""
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


def read_main_cookie():
    """🍪 v0.17: значение .ROBLOSECURITY с ГЛАВНОГО Roblox (Дельта) или None."""
    for db in _cookie_db_candidates(PACKAGE_MAIN):
        if not run_su(f"test -f '{db}'")[0]:
            continue
        _copy_check_db(db)
        con = None
        try:
            con = sqlite3.connect(CHECK_DB)
            has = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name='cookies'").fetchone()
            if not has:
                continue
            for r in con.execute("SELECT value FROM cookies "
                                 "WHERE name='.ROBLOSECURITY'").fetchall():
                v = (r[0] or "").strip()
                if len(v) > 40:
                    return v
        except Exception:
            pass
        finally:
            if con:
                try:
                    con.close()
                except Exception:
                    pass
            _clean_check_db()
    return None


def main_cookie_valid():
    """🍪 v0.17: на главном Roblox есть ЖИВОЙ акк (кука есть И API отвечает 200).
    Одного наличия куки мало: протухшая/разлогиненная кука проходит has_session,
    но Дельта с ней на плейс НЕ зайдёт → байпас вхолостую.
    Ошибка сети/чтения → True (не блокируем байпас из-за самой проверки)."""
    try:
        cookie = read_main_cookie()
    except Exception as e:
        log(f"⚠️ Чтение куки главного Roblox упало ({e}) — пропускаю проверку")
        return True
    if not cookie:
        log("🍪 Главный Roblox (Дельта): куки НЕТ вовсе → акка нет")
        return False
    status, uid, name = _roblox_auth_check(cookie)
    if status == "ok":
        log(f"🍪 Главный Roblox: акк ЖИВОЙ ({name}, id {uid})")
        return True
    if status == "dead":
        log("🍪 Главный Roblox: кука есть, но ПРОТУХЛА (API 401) — акка фактически нет")
        return False
    log("🍪 Главный Roblox: не удалось проверить куку (сеть/timeout) — не блокирую")
    return True


def missing_cookies_reason():
    """🍪 None — кук достаточно для байпаса и фарма.
    Иначе строка-причина, по которой нужна авторегистрация:
      • нет куки на Дельте (main)  → байпас не сделается;
      • ВСЕ клоны без сессий       → фармить нечем.
    Частичная убыль кук → None (фарм работает, починку делает check/рега)."""
    if not has_session(PACKAGE_MAIN):
        return "нет куки на Дельте (com.roblox.client) — байпас не работает"
    farm_pkgs = get_farm_packages()
    if farm_pkgs:
        with_sess = sum(1 for p in farm_pkgs if has_session(p))
        if with_sess == 0:
            return f"в клонах нет куки (0/{len(farm_pkgs)}) — фармить нечем"
    return None


def _rega_pid():
    """pid живой рега-сервис или None (pid-файл пишет PM, клиент или мы)."""
    try:
        pid = int((FARM_BASE / "info" / "pids" / "rega.pid").read_text().strip())
        cl = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        if "rega/main.py" in cl.replace("\x00", " "):
            return pid
    except Exception:
        pass
    return None


def _clear_rega_pid(pid):
    try:
        p = FARM_BASE / "info" / "pids" / "rega.pid"
        if p.exists() and p.read_text().strip() == str(pid):
            p.unlink()
    except Exception:
        pass


def _lock_busy():
    """True — flock info/rega.lock кто-то держит (рега/check уже идёт).
    Проба без записи: взяли → отпустили. Чужой лок не трогаем."""
    try:
        fd = os.open(str(REGA_LOCK), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)
    except OSError:
        return True


def stop_rega(timeout_s=8):
    """🛑 Полный стоп: фарм ⏹ глушит и регу (services/rega, включая check).
    SIGTERM (у рега мягкий хендлер) → ждём до timeout_s → SIGKILL + чистка
    pid-файла. False — рега и не шла."""
    pid = _rega_pid()
    if not pid and not _lock_busy():
        return False
    log(f"🛑 Полный стоп: глушу регу{f' (pid {pid})' if pid else ''}...")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    # — и махом по всем rega/main.py (в т.ч. check без pid-файла;
    #   [.] не даёт pkill убить сам su-процесс)
    run_su("pkill -TERM -f 'services/rega/main[.]py'", timeout=5)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _rega_pid() and not _lock_busy():
            log("   ✅ Рега остановлена")
            if pid:
                _clear_rega_pid(pid)
            return True
        time.sleep(0.5)
    log("   ⚠️ Рега не вышла — добиваю SIGKILL")
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    run_su("pkill -9 -f 'services/rega/main[.]py'", timeout=5)
    try:
        (FARM_BASE / "info" / "pids" / "rega.pid").unlink(missing_ok=True)
    except Exception:
        pass
    return True


def rega_enabled_locally() -> bool:
    """🛡 v0.20: включена ли рега акков НА ЭТОМ телефоне. Файл пишет КЛИЕНТ
    (задача rega.switch с сервера — тумблер дашборда + hello-sync).
    Файла нет = ВЫКЛЮЧЕНА — безопасный режим по умолчанию: акки с лутом
    защищены от случайной перерегистрации."""
    try:
        return bool(json.loads(REGA_SWITCH_FILE.read_text()).get("enabled"))
    except Exception:
        return False


def handle_no_cookies(reason="нет кук"):
    """🍪 Кук нет (reason — почему) → сначала авторегистрация, потом байпас/фарм.
    Если рега уже идёт (запущена сервером/клиентом) — просто ждём её.
    🛡 v0.20: kill-switch выключен → авторегистрация НЕ запускается:
    пишем событие и ждём (60с), фарм клонами продолжается как может."""
    if not rega_enabled_locally():
        log("🛡 Рега акков ОТКЛЮЧЕНА (safe-режим) — авторегистрацию НЕ запускаю")
        # 🛡 v0.23: событие раз в 30 мин (раньше — каждую минуту: 60 событий/час
        # забивали ленту 📅 и мешали видеть реальное состояние)
        if time.time() - _last_blocked_emit[0] > 1800:
            _last_blocked_emit[0] = time.time()
            emit("rega.blocked", reason=reason[:120],
                 note="рега отключена kill-switch — акки с лутом защищены")
        time.sleep(60)
        return
    log(f"🆘 Кук нет ({reason}) — байпас и фарм отложены: сначала авторегистрация")
    emit("farm.no_cookies", reason=reason[:120])
    kill_all_roblox()

    for attempt in (1, 2):
        # 🛡 v0.23: повторная проверка тумблера перед КАЖДЫМ спавном —
        # пользователь мог выключить регу, пока мы ждали лок/идущую регу
        if not rega_enabled_locally():
            log("🛡 Рега отключена тумблером (kill-switch) во время ожидания — отменяю")
            emit("rega.blocked", reason="switch off during wait", note="kill-switch сработал между попытками")
            return
        pid = _rega_pid()
        if pid:
            log(f"🕒 Рега уже идёт (pid {pid}) — жду окончания...")
            waited = 0
            while _rega_pid() and waited < REGA_WAIT_MAX:
                time.sleep(30)
                waited += 30
            break
        log("🚀 Запускаю авторегистрацию (services/rega)...")
        (FARM_BASE / "logs" / "services").mkdir(parents=True, exist_ok=True)
        logf = open(FARM_BASE / "logs" / "services" / "rega.log", "ab")
        proc = subprocess.Popen(
            [sys.executable, str(REGA_SCRIPT)],
            cwd=str(FARM_BASE), stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True)
        try:
            (FARM_BASE / "info" / "pids").mkdir(parents=True, exist_ok=True)
            (FARM_BASE / "info" / "pids" / "rega.pid").write_text(str(proc.pid))
        except Exception:
            pass
        emit("farm.rega_started", pid=proc.pid)
        waited = 0
        while proc.poll() is None and waited < REGA_WAIT_MAX:
            time.sleep(10)
            waited += 10
        _clear_rega_pid(proc.pid)
        if proc.returncode == 99 and attempt == 1:
            # лок держит другая рега/check — ждём освобождения и спавним ещё раз
            log("🔒 Лок рега занят другой регой/check — жду освобождения...")
            waited = 0
            while _lock_busy() and waited < REGA_WAIT_MAX:
                time.sleep(30)
                waited += 30
            continue
        log(f"🏁 Рега завершилась (ждал {waited // 60} мин)")
        break

    # тот же гейт, что и в main(): рега обязана закрыть ОБЕ части фермы
    try:
        left = missing_cookies_reason()
    except Exception:
        left = None
    # 🆕 v0.18: НАЛИЧИЯ куки мало — протухшая кука main проходит has_session,
    # и handle отчитывался успехом → фарм крутил «рега↔гейт» по кругу не понимая,
    # что чинить. Главный акк проверяем ЧЕСТНО (через Roblox API).
    if left is None:
        try:
            if not main_cookie_valid():
                left = "главный Roblox без живого акка (кука протухла)"
        except Exception:
            left = None
    if left is None:
        log(f"✅ Куки есть (сессий {total_sessions()}) — продолжаю: байпас → фарм")
        emit("farm.rega_done", sessions=total_sessions())
    else:
        log(f"⚠️ Рега не дала нужных кук ({left}) — пауза "
            f"{REGA_RETRY_PAUSE // 60} мин и новая попытка")
        emit("farm.rega_empty", reason=left[:120])
        time.sleep(REGA_RETRY_PAUSE)


def _bypass_gate_ok():
    """🍪 v0.18: True — акк главного Roblox жив, байпас можно делать.
    False — акка нет: рега запущена/отработала, ждём (флаг кнопки НЕ трогаем).
    Счётчик подряд неудачных починок (защита от вечного круга «рега↔гейт»,
    когда рега не может дать живую куку — пул пуст/регистрация не идёт):
      3 подряд → пауза 2ч, чтобы не гонять регу впустую;
      6 подряд → считаем акк неспасаемым сейчас, сбрасываем флаг кнопки и
                 живём дальше (фарм клонами работает и без байпаса)."""
    try:
        main_ok = main_cookie_valid()
    except Exception as e:
        log(f"⚠️ Проверка акка главного Roblox упала ({e}) — веду как раньше")
        return True
    if main_ok:
        if state.get("no_cookie_fails"):
            state["no_cookie_fails"] = 0
            save_state()
        return True

    log("🍪 Главный Roblox без живого акка — байпас ОТЛОЖЕН, запускаю регу акков")
    try:
        handle_no_cookies("нет живой куки на главном Roblox перед байпасом")
    except Exception as e:
        log(f"💥 Куки-гейт перед байпасом упал: {e}")
        time.sleep(300)

    # починка кончилась — проверяем ЧЕСТНО: кука ожила?
    try:
        still_dead = not main_cookie_valid()
    except Exception:
        still_dead = False
    if not still_dead:
        state["no_cookie_fails"] = 0
        save_state()
        return False   # кука ожила — но на этом проходе байпас не делаем, следующий пройдёт гейт без рега

    fails = state.get("no_cookie_fails", 0) + 1
    state["no_cookie_fails"] = fails
    save_state()
    if fails >= 6:
        log("🧯 Акк главного Roblox не спасён 6 починок подряд — сбрасываю флаг байпаса, "
            "продолжаю без него (фарм клонами не зависит от байпаса)")
        emit("bypass.flag_dropped", fails=fails,
             reason="акк главного Roblox не починен за 6 рег — флаг кнопки сброшен")
        try:
            BYPASS_FORCE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        state["no_cookie_fails"] = 0
        save_state()
    elif fails >= 3:
        log(f"🧯 Починок без живого акка подряд: {fails}/6 — пауза 2ч, чтобы не гонять регу впустую")
        emit("farm.no_cookies_stuck", fails=fails)
        time.sleep(7200)
    return False


# ==========================================
# 🔗 БАЙПАС — ПОЛНЫЙ ПОРТ ИЗ v18.8 (скрипт хозяина)
# 9 попыток (6 обычных + 3 с двойным кликом), координаты в ландшафте,
# ZEN-API с разбором link/ключ и ретраями 429, буфер в 3 способа,
# открытие ссылки в 4 фоллбэка, чтение ключа в 4 способа.
# ==========================================

# --- 📋 буфер обмена (termux-api + фоллбэки) ---
TERMUX_GET = ("termux-clipboard-get",
              "/data/data/com.termux/files/usr/bin/termux-clipboard-get")
TERMUX_SET = ("termux-clipboard-set",
              "/data/data/com.termux/files/usr/bin/termux-clipboard-set")


def termux_clipboard_get():
    for cmd in TERMUX_GET:
        try:
            res = subprocess.run([cmd], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
    return None


def termux_clipboard_set(text):
    for cmd in TERMUX_SET:
        try:
            res = subprocess.run([cmd], input=text, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return True
        except Exception:
            pass
    return False


# --- 🔎 распознавание ссылок ---
def _looks_like_url(t):
    if not t:
        return False
    t = t.strip()
    if len(t) < 8:
        return False
    if t.startswith("http") or "://" in t:
        return True
    if re.match(r'^(www\.)?[a-z0-9-]+\.[a-z]{2,}([/?].*)?$', t, re.I):
        return True
    if re.search(r'(lootlabs|linkvertise|work\.ink|izen|zen\.lol|\.gg/|\.ink/|relay|platorelay)', t, re.I):
        return True
    return False


def _normalize_url(t):
    t = t.strip()
    return t if t.startswith("http") else "https://" + t


def get_visible_url():
    for t in get_visible_text():
        if _looks_like_url(t):
            return t
    return ""


# --- 📋 чтение буфера: termux-api → service call parcel → вставка + дамп ---
def _extract_url_from_parcel(hexdump):
    tokens = re.findall(r'\b[0-9a-fA-F]{8}\b', hexdump)
    if not tokens:
        return None
    try:
        data = b''.join(bytes.fromhex(t)[::-1] for t in tokens)
    except ValueError:
        return None
    text = data.decode('utf-16-le', errors='ignore')
    m = re.search(r'https?://[^\s\x00-\x1f]+', text)
    return m.group(0) if m else None


def _read_via_paste_dump():
    log("📋 Читаю буфер через вставку + дамп экрана...")
    run_su(f"input tap {OMNIBOX_TAP[0]} {OMNIBOX_TAP[1]}")
    time.sleep(1.5)
    run_su("input keyevent 279")  # PASTE
    time.sleep(2)
    for attempt in range(3):
        u = get_visible_url()
        if u:
            log(f"   🎯 Найдено в дампе: {u}")
            return _normalize_url(u)
        log(f"   ♻️ Дамп пуст, попытка {attempt + 2}/3...")
        time.sleep(2)
    return ""


def get_clipboard():
    t = termux_clipboard_get()
    if t and _looks_like_url(t):
        return _normalize_url(t)

    for cmd in (
        "service call clipboard 2 s16 com.termux i32 0",
        "service call clipboard 2 s16 com.termux s16 com.termux i32 0",
        "service call clipboard 2 i32 0",
    ):
        ok, out, _ = run_su(cmd, timeout=5)
        if ok:
            url = _extract_url_from_parcel(out)
            if url:
                log(f"   🎯 Прочитано через service call: {url}")
                return url

    return _read_via_paste_dump()


# --- 🔑 чтение ключа лицензии (FREE_xxx) — 4 способа, как в v18.8 ---
_CLIP_PARCEL_CMDS = (
    "service call clipboard 2 s16 com.termux i32 0",
    "service call clipboard 2 s16 com.termux s16 com.termux i32 0",
    "service call clipboard 2 i32 0",
)


def get_copied_key():
    force_landscape("Чтение ключа в браузере")   # 🆕 v0.16: омнибокс-тап по ландшафтным координатам
    time.sleep(2)

    t = termux_clipboard_get()
    if t:
        m = KEY_RE.search(t)
        if m:
            log(f"   🎯 Ключ через termux-api: {m.group(1)}")
            return m.group(1)
        if ACCEPT_LOOSE_KEY and not _looks_like_url(t) and 5 < len(t) <= 200:
            log(f"   ⚠️ LOOSE-ключ из буфера: {t[:40]}...")
            return t.strip()

    for cmd in _CLIP_PARCEL_CMDS:
        ok, out, _ = run_su(cmd, timeout=5)
        if ok:
            tokens = re.findall(r'\b[0-9a-fA-F]{8}\b', out)
            if tokens:
                try:
                    data = b''.join(bytes.fromhex(tk)[::-1] for tk in tokens)
                except ValueError:
                    continue
                text = data.decode('utf-16-le', errors='ignore').replace('\x00', ' ')
                m = KEY_RE.search(text)
                if m:
                    log(f"   🎯 Ключ через service call: {m.group(1)}")
                    return m.group(1)
                if ACCEPT_LOOSE_KEY:
                    stripped = text.strip()
                    if stripped and not _looks_like_url(stripped) and 5 < len(stripped) <= 200:
                        log(f"   ⚠️ LOOSE-ключ из parcel: {stripped[:40]}...")
                        return stripped

    log("🔑 Ищу ключ на экране (дамп)...")
    for t in get_visible_text():
        m = KEY_RE.search(t)
        if m:
            log(f"   🎯 Ключ на экране: {m.group(1)}")
            return m.group(1)

    log("🔑 Вставляю буфер в адресную строку и читаю дамп...")
    run_su(f"input tap {OMNIBOX_TAP[0]} {OMNIBOX_TAP[1]}")
    time.sleep(1)
    run_su("input keyevent 279")  # PASTE
    time.sleep(1.5)
    for t in get_visible_text():
        m = KEY_RE.search(t)
        if m:
            log(f"   🎯 Ключ из вставки: {m.group(1)}")
            return m.group(1)

    if ACCEPT_LOOSE_KEY:
        candidates = [t for t in get_visible_text() if not _looks_like_url(t) and 10 < len(t) <= 200]
        if candidates:
            candidates.sort(key=len, reverse=True)
            log(f"   ⚠️ LOOSE-ключ с экрана: {candidates[0][:40]}...")
            return candidates[0]

    return None


# --- 🌐 ZEN-API (полный разбор ответа v18.8) ---
def zen_bypass(original_link, _retry=0):
    """Возвращает ("link", url) | ("key", key) | None."""
    log(f"🔗 Запрос к ZEN-API: {original_link[:60]}...")
    headers = {"x-api-key": ZEN_API_KEY, "User-Agent": "FarmBot/18.8"}
    endpoint = f"{ZEN_API_URL}?url={urllib.parse.quote(original_link, safe='')}"

    code, body = None, ""
    try:
        req = urllib.request.Request(endpoint, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.status
            body = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
    except urllib.error.URLError:
        log("🌐 Ошибка соединения")
        return None
    except Exception as e:
        log(f"⏰ Запрос не удался: {type(e).__name__}: {e}")
        return None

    log(f"📥 HTTP {code}")
    if code == 429:
        if _retry >= 3:
            log("❌ Слишком много 429 — отмена запроса")
            return None
        log("⏳ Rate limit, жду 60с...")
        time.sleep(60)
        return zen_bypass(original_link, _retry + 1)
    if code != 200:
        log(f"❌ HTTP {code}: {body[:100]}")
        return None

    try:
        data = json.loads(body)
    except ValueError:
        log(f"❌ Некорректный JSON: {body[:100]}")
        return None
    log(f"📥 API: {str(data)[:200]}")

    raw = data.get("result") or data.get("destination") or data.get("link")
    if isinstance(raw, dict):
        raw = raw.get("url") or raw.get("link") or raw.get("destination") or ""
    result = str(raw).strip() if raw else ""

    if result:
        if result.startswith("http"):
            return ("link", result)
        m = KEY_RE.search(result)
        if m:
            return ("key", m.group(1))
        m = re.search(r'(https?://[^\s"\']+)', result)
        if m:
            return ("link", m.group(0))

    m = re.search(r'(https?://[^\s"\']+)', body)
    if m:
        return ("link", m.group(0))
    return None


# --- 🌐 открытие длинного bypass-URL: am start → paste → чанки → посимвольно ---
def inject_url_via_ui(url):
    if not url:
        return False
    force_landscape("Переход на сайт bypass")   # 🆕 v0.16: браузер всегда горизонтально
    log(f"🌐 Открываю bypass-ссылку ({len(url)} символов)...")
    host = re.sub(r'^https?://', '', url).split('/')[0].split(':')[0].lower()

    escaped = url.replace("'", "'\\''")
    ok, _, err = run_su(f"am start -a android.intent.action.VIEW -d '{escaped}'", timeout=10)
    if ok:
        log("   ✅ am start выполнен, жду загрузку...")
        time.sleep(5)
        force_landscape("Браузер открыт")   # 🆕 v0.16: Chrome мог сбросить поворот при открытии
        if any(host in t.lower() for t in get_visible_text()):
            log(f"   ✅ Домен {host} на экране — страница открыта")
            return True
        vis = get_visible_url().lower()
        if host in vis:
            log("   ✅ Домен виден в адресной строке")
            return True
        log("   ⚠️ Домен не найден после am start, пробую ввод в строку...")
    else:
        log(f"   ⚠️ am start ошибка: {err}")

    termux_clipboard_set(url)
    esc = url.replace("'", "'\\''")
    run_su(f"am broadcast -a clipper.set -e text '{esc}'", timeout=5)

    tap(*OMNIBOX_TAP, 0.3, "OMNIBOX (1)")
    tap(*OMNIBOX_TAP, 0.3, "OMNIBOX (2)")
    tap(*OMNIBOX_TAP, 0.5, "OMNIBOX (3)")
    time.sleep(1)
    select_all_delete()
    run_su("input keyevent 279", timeout=5)  # PASTE
    time.sleep(1.5)
    vis = get_visible_url()
    log(f"   🔎 В строке: {vis[:60]}... ({len(vis)}/{len(url)})")
    if host in vis.lower() and len(vis) >= len(url) * 0.8:
        run_su("input keyevent 66", timeout=5)  # ENTER
        time.sleep(1)
        log("   ✅ URL вставлен полностью и открыт")
        return True

    log("📝 Вставляю частями по 150 символов...")
    select_all_delete()
    chunks = [url[i:i + 150] for i in range(0, len(url), 150)]
    all_ok = True
    for ch in chunks:
        safe = ch.replace("'", "'\\''").replace(" ", "%s")
        ok2, _, _ = run_su(f"input text '{safe}'", timeout=10)
        if not ok2:
            all_ok = False
            break
        time.sleep(0.15)
    if all_ok:
        run_su("input keyevent 66", timeout=5)
        time.sleep(1)
        log("   ✅ Чанковый ввод завершён")
        return True

    log("🔡 Крайний случай: посимвольный ввод...")
    select_all_delete()
    for ch in url:
        low = ch.lower()
        if 'a' <= low <= 'z':
            code = 29 + (ord(low) - ord('a'))
            if ch.isupper():
                run_su(f"input keycombination 59 {code}", timeout=3)
            else:
                run_su(f"input keyevent {code}", timeout=3)
        elif '0' <= low <= '9':
            run_su(f"input keyevent {7 + (ord(low) - ord('0'))}", timeout=3)
        elif low == '-':
            run_su("input keyevent 69", timeout=3)
        elif low == '_':
            run_su("input keycombination 59 69", timeout=3)
        elif low == '.':
            run_su("input keyevent 56", timeout=3)
        elif low == '/':
            run_su("input keyevent 76", timeout=3)
        elif low == ':':
            run_su("input keycombination 59 74", timeout=3)
        elif low == '?':
            run_su("input keycombination 59 76", timeout=3)
        elif low == '=':
            run_su("input keyevent 70", timeout=3)
        elif low == '&':
            run_su("input keycombination 59 14", timeout=3)
        elif low == '%':
            run_su("input keycombination 59 12", timeout=3)
        elif low == '#':
            run_su("input keycombination 59 10", timeout=3)
        elif low == '+':
            run_su("input keyevent 78", timeout=3)
        elif low == '@':
            run_su("input keyevent 77", timeout=3)
        elif low == ';':
            run_su("input keyevent 74", timeout=3)
        elif low == ',':
            run_su("input keyevent 55", timeout=3)
        elif low == ' ':
            run_su("input keyevent 62", timeout=3)
        else:
            # неизвестный символ — input text, чтобы URL не обрезался
            esc3 = ch.replace("\\", "\\\\").replace("'", "'\\''")
            run_su(f"input text '{esc3}'", timeout=3)
        time.sleep(0.02)
    run_su("input keyevent 66", timeout=5)
    time.sleep(1)
    return True


def inject_key(key):
    """💾 Запись ключа в файл license + честная проверка read-back (v18.8)."""
    if not key:
        log("❌ Ключ пустой")
        return False
    log(f"💉 ЗАПИСЬ КЛЮЧА В ФАЙЛ: {DELTA_LICENSE_PATH}")
    log(f"   🔑 Ключ: {key}")
    try:
        folder = os.path.dirname(DELTA_LICENSE_PATH)
        if not os.path.exists(folder):
            run_su(f"mkdir -p '{folder}'", timeout=5)
            log(f"   📁 Создана папка: {folder}")
        try:
            with open(DELTA_LICENSE_PATH, 'w') as f:
                f.write(key)
            log("✅ Ключ записан через Python")
        except PermissionError:
            log("⚠️ Нет прав через Python, пишу через su...")
            escaped_key = key.replace("'", "'\"'\"'")
            ok, out, err = run_su(f"echo '{escaped_key}' > '{DELTA_LICENSE_PATH}'", timeout=5)
            if not ok:
                log(f"❌ Ошибка записи через su: {err}")
                return False
            log("✅ Ключ записан через su")
        run_su(f"chmod 644 '{DELTA_LICENSE_PATH}'", timeout=3)
        try:
            with open(DELTA_LICENSE_PATH, 'r') as f:
                content = f.read().strip()
            if content == key:
                log("✅ Ключ успешно проверен в файле")
            else:
                log(f"❌ Содержимое файла отличается: '{content[:20]}...' — запись НЕ засчитана")
                return False
        except Exception as e:
            log(f"⚠️ Не удалось проверить файл (нужен su для чтения?): {e}")
        return True
    except Exception as e:
        log(f"❌ Ошибка записи файла: {e}")
        return False


def run_bypass_attempt(attempt, total, use_double_click=False):
    """🔁 Одна попытка байпаса — UI-флоу v18.8 (координаты, ландшафт)."""
    mode = "🔥 ДВОЙНОЙ КЛИК CLOSE_AD" if use_double_click else "обычные клики"
    log(f"\n{'=' * 50}\n🔁 БАЙПАС {attempt}/{total} [{mode}]\n{'=' * 50}")

    try:
        kill_all_roblox()
        wake_screen()
        force_landscape("Байпас: старт попытки")   # 🆕 v0.16: ландшафт ДО запуска Дельты
        launch_delta()
        log(f"⏳ Ждем {UI_INITIAL_DELAY}с загрузки MM2...")
        time.sleep(UI_INITIAL_DELAY)

        force_landscape("Клик GET KEY в Дельте")   # 🆕 v0.16: координаты ЛАНДШАФТНЫЕ — поворот ДО клика
        tap(*LINK_TAP, UI_STEP_DELAYS["LINK_TAP"], "LINK_TAP")
        set_landscape()
        time.sleep(UI_STEP_DELAYS["SET_LANDSCAPE"])
        tap(*CLOSE_TRANSL_1, UI_STEP_DELAYS["CLOSE_TRANSL_1"], "CLOSE_TRANSL_1")
        tap(*TRIGGER_AD, UI_STEP_DELAYS["TRIGGER_AD"], "TRIGGER_AD")

        if use_double_click:
            log(f"👆👆 ДВОЙНОЙ КЛИК CLOSE_AD {CLOSE_AD}")
            tap(*CLOSE_AD, DBLCLICK_GAP, "CLOSE_AD (двойной 1/2)")
            tap(*CLOSE_AD, UI_STEP_DELAYS["CLOSE_AD"], "CLOSE_AD (двойной 2/2)")
        else:
            tap(*CLOSE_AD, UI_STEP_DELAYS["CLOSE_AD"], "CLOSE_AD")

        tap(*CONTINUE_1, UI_STEP_DELAYS["CONTINUE_1"], "CONTINUE_1")
        tap(*GOOGLE_ROW, UI_STEP_DELAYS["GOOGLE_ROW"], "GOOGLE_ROW")
        tap(*COPY_LINK, UI_STEP_DELAYS["COPY_LINK"], "COPY_LINK")

        log(f"⏳ Даю ссылке {COPY_SETTLE_DELAY}с на копирование...")
        time.sleep(COPY_SETTLE_DELAY)

        copied_link = get_clipboard()
        if copied_link:
            log(f"📋 Исходная ссылка: {copied_link[:70]}")
        if not copied_link or not _looks_like_url(copied_link):
            log("⚠️ Ссылка не получена, повтор (ландшафт НЕ сбрасываю — v0.16 всегда горизонтально)...")
            time.sleep(3)
            return None
        copied_link = _normalize_url(copied_link)

        zen = zen_bypass(copied_link)
        if not zen:
            log("❌ API не дал результат, повтор (ландшафт НЕ сбрасываю — v0.16 всегда горизонтально)...")
            time.sleep(5)
            return None
        kind, value = zen

        if kind == "key":
            log(f"🎯 API отдал КЛЮЧ напрямую: {value[:50]}...")
            kill_all_roblox()
            time.sleep(2)
            return value

        log(f"✅ Bypass-ссылка: {value[:60]}... ({len(value)} символов)")
        if not inject_url_via_ui(value):
            log("⚠️ URL не открылся, повтор (ландшафт НЕ сбрасываю — v0.16 всегда горизонтально)...")
            time.sleep(3)
            return None

        log(f"⏳ {UI_STEP_DELAYS['OPEN_ZEN_LINK']}с загрузки страницы...")
        time.sleep(UI_STEP_DELAYS["OPEN_ZEN_LINK"])

        force_landscape("Сайт GET KEY: клики по сайту")   # 🆕 v0.16: браузер всегда горизонтально
        tap(*CONTINUE_KEY, UI_STEP_DELAYS["CONTINUE_KEY"], "CONTINUE_KEY")
        tap(*CLOSE_TRANSL_2, UI_STEP_DELAYS["CLOSE_TRANSL_2"], "CLOSE_TRANSL_2")
        tap(*COPY_CODE, UI_STEP_DELAYS["COPY_CODE"], "COPY_CODE")

        log("⏳ Даю ключу 3с на копирование...")
        time.sleep(3)
        key = get_copied_key()

        kill_all_roblox()
        time.sleep(2)

        if not key:
            log("❌ Ключ не получен, повтор...")
            time.sleep(5)
            return None

        return key
    except SystemExit:
        # фарм ⏹ (SIGTERM): выходим, ландшафт НЕ трогаем (v0.16: всегда горизонтально)
        raise


def run_bypass_cycle():
    """🚀 Цикл байпаса v18.8: 6 обычных + 3 с двойным кликом = 9 попыток."""
    total = BYPASS_CLICK_RETRIES + BYPASS_DBLCLICK_RETRIES

    # 🍪 v0.17: без ЖИВОГО акка на главном Roblox Дельта не зайдёт на плейс —
    # 9 попыток вхолостую не тратим, сразу сигнал что нужна рега/починка кук
    if not main_cookie_valid():
        log("🍪 БАЙПАС ОТМЕНЁН: на главном Roblox нет живого акка (без него на плейс не зайти)")
        emit("bypass.no_account", reason="нет живой куки на главном Roblox — без акка на плейс не зайти")
        emit("bypass.fail", retries=0, reason="no_account_main")
        return False

    emit("bypass.start", attempts=total)
    log(f"🚀 ЦИКЛ БАЙПАСА: {BYPASS_CLICK_RETRIES} обычных + {BYPASS_DBLCLICK_RETRIES} двойных = {total} попыток")

    for i in range(1, BYPASS_CLICK_RETRIES + 1):
        key = run_bypass_attempt(i, total, use_double_click=False)
        if key:
            if inject_key(key):
                state["last_key_time"] = time.time()
                save_state()
                emit("bypass.ok", key=key[:14] + "…", attempt=i, mode="click")
                log("💾 Таймер байпаса обновлён")
                return True
            log("⚠️ Ключ НЕ записан в license — попытка не засчитана")

    for i in range(1, BYPASS_DBLCLICK_RETRIES + 1):
        key = run_bypass_attempt(BYPASS_CLICK_RETRIES + i, total, use_double_click=True)
        if key:
            if inject_key(key):
                state["last_key_time"] = time.time()
                save_state()
                emit("bypass.ok", key=key[:14] + "…", attempt=BYPASS_CLICK_RETRIES + i, mode="dblclick")
                log("💾 Таймер байпаса обновлён")
                return True
            log("⚠️ Ключ НЕ записан в license — попытка не засчитана")

    log(f"💥 Все {total} попыток байпасса провалены (ландшафт остаётся — v0.16)")
    kill_all_roblox()
    emit("bypass.fail", retries=total)
    return False


# ==========================================
# ▶️ MAIN
# ==========================================

def main():
    signal.signal(signal.SIGTERM, _sigterm)

    log("🤖 Roblox Farm SERVICE START (farm v16.2 + байпас v18.8 ТОЛЬКО по задаче сервера v0.26 + ключ ≥23ч + сбор-трейд v0.24 HOLD «НОВЫЙ ЦИКЛ» + приватки v0.22: зашитый фолбэк, services/farm)")
    log(f"   su: {SU_BIN}")
    log(f"🔗 ZEN-API: {'✅' if ZEN_API_KEY and ZEN_API_KEY != 'YOUR_API_KEY_HERE' else '❌ Не настроен'}")
    log(f"📁 Delta Lua: {DELTA_AUTOEXEC_PATH}")
    log(f"📁 Delta License: {DELTA_LICENSE_PATH}")
    log(f"💾 State: {STATE_FILE}")
    log(f"⏱️ Фарм: {FARM_CYCLE_SECONDS//60} мин | 🔓 Байпас: ТОЛЬКО по задаче сервера (bypass.run) и только если ключу ≥{BYPASS_MIN_KEY_AGE_H:.0f}ч ({BYPASS_CLICK_RETRIES}+{BYPASS_DBLCLICK_RETRIES} попыток)")
    log(f"🔍 Мониторинг фермы: каждые {FARM_CHECK_INTERVAL} сек")
    log(f"⏳ Задержка перед запуском: {FARM_PRELAUNCH_DELAY} сек")
    log(f"🔄 Задержка перед перезапуском: {FARM_RESTART_DELAY} сек")

    log("\n" + "="*50)
    log("🔥 ШАГ 1: ПЕРЕЗАПИСЬ DELTA LUA")
    log("="*50)
    if create_delta_lua():
        log("✅ Lua файл готов к использованию\n")
    else:
        log("⚠️ Lua файл не удалось перезаписать, но продолжаем\n")

    load_state()
    emit("farm.start", pid=os.getpid(),
         last_key_age_h=round((time.time() - state.get("last_key_time", 0)) / 3600, 1))

    while True:
        # 🌾 ОКНО СБОРА — ПЕРВЫМ ДЕЛОМ (v0.20): сбору нужны только куки КЛОНОВ,
        # а куки-гейт ниже требует ещё и живой акк Дельты. Раньше мёртвый main
        # блокировал сбор навсегда (с отключенной регой — тем более).
        hw = harvest_window()
        if hw:
            res = None
            try:
                res = run_harvest_session(hw)
            except Exception as e:
                log(f"💥 Сбор упал: {e}")
                emit("harvest.fail", error=str(e)[:200])
                try:
                    kill_all_roblox()
                    create_delta_lua()   # вернуть фарм-скрипт при любом падении
                except Exception:
                    pass
            if res == "bypass":
                # 🔓 v0.18: сбор прерван кнопкой — байпас СЕЙЧАС. Раньше флаг
                # не съедался здесь → сбор запускался снова → монитор снова
                # видел флаг → вечный круг, байпас не выполнялся никогда.
                # 🔓 v0.26: ПРАВИЛО ХОЗЯИНА — ключ ≥23ч (или force во флаге).
                if _bypass_gate_ok():
                    ok_age, age = bypass_key_old_enough()
                    if (data := consume_bypass_request()) is not None:
                        if data.get("force") or ok_age:
                            log("🔓 Байпас по кнопке ПРЯМО ВО ВРЕМЯ окна сбора...")
                            run_bypass_cycle()
                        else:
                            log(f"⏳ Байпас отклонён: ключу {age:.1f}ч < "
                                f"{BYPASS_MIN_KEY_AGE_H:.0f}ч (правило хозяина)")
                            emit("bypass.skipped_fresh", age_h=round(age, 1),
                                 min_h=BYPASS_MIN_KEY_AGE_H, where="harvest")
            continue

        # 🍪 КУКИ-ГЕЙТ (v0.12): без куки Дельты байпас не сделается,
        # без кук на клонах фармить нечем → сначала рега акков
        try:
            reason = missing_cookies_reason()
        except Exception as e:
            log(f"⚠️ Проверка сессий упала ({e}) — считаю что куки есть")
            reason = None
        if reason:
            try:
                handle_no_cookies(reason)
            except Exception as e:
                log(f"💥 Куки-гейт упал: {e}")
                time.sleep(300)
            continue

        now = time.time()
        elapsed = now - state["last_key_time"]

        # 🔓 v0.25: БАЙПАС — ТОЛЬКО ПО ЗАДАЧЕ СЕРВЕРА (кнопка 🔓 → bypass.run →
        # bypass_force.json). САМОНАЗНАЧЕНИЕ УДАЛЕНО (жалоба хозяина 25.10:
        # «в 20 мин он начал делать байпас, хотя я всё остановил» — это был
        # авто-байпас по кулдауну 24ч). Возраст ключа больше ни на что не
        # влияет: нет задачи с сервера — байпас не запускается, фарм работает.
        # Флаг кнопки НЕ забираем до проверки гейта — если акка нет, флаг
        # остаётся, рега чинит куки и байпас выполнится на следующем проходе.
        # 🔓 v0.26: ПРАВИЛО ХОЗЯИНА — байпас ТОЛЬКО если ключу ≥23ч (или ключа
        # не было вовсе). Свежий ключ → флаг снимаем и честно пишем событие:
        # гонять 9 попыток рекламы ради ключа, которому ещё 5ч, — пустая трата
        # телефона. force:true во флаге (владелец нажал FORCE) идёт мимо правила.
        if bypass_requested():
            if not _bypass_gate_ok():
                continue  # флаг байпаса не тронут — выполнится после рега
            ok_age, age = bypass_key_old_enough()
            if (data := consume_bypass_request()) is not None:
                if data.get("force") or ok_age:
                    log("🔓 Байпас по ЗАДАЧЕ СЕРВЕРА (bypass.run) — полный цикл v18.8: "
                        "Delta → реклама → ZEN-API → ключ → license")
                    kill_all_roblox()
                    run_bypass_cycle()
                else:
                    log(f"⏳ Байпас ОТКЛОНЁН: ключу {age:.1f}ч < "
                        f"{BYPASS_MIN_KEY_AGE_H:.0f}ч — байпас не нужен "
                        f"(правило хозяина: байпас только по ключу >23ч)")
                    emit("bypass.skipped_fresh", age_h=round(age, 1),
                         min_h=BYPASS_MIN_KEY_AGE_H, where="main")
        else:
            age = f"{elapsed/3600:.1f}ч" if state["last_key_time"] > 0 else "нет ключа"
            log(f"⏱️ Возраст ключа: {age} → байпас сам НЕ запускаю "
                f"(только по кнопке 🔓 / bypass.run с сервера)")

        kill_all_roblox()
        farm_pkgs = launch_roblox_light_farm()
        emit("farm.cycle", packages=len(farm_pkgs), hours=FARM_CYCLE_SECONDS // 3600)
        log(f"💤 Фарм {FARM_CYCLE_SECONDS//60} мин с мониторингом каждые {FARM_CHECK_INTERVAL} сек...")
        monitor_farm(FARM_CYCLE_SECONDS, farm_pkgs)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("🛑 Остановлено пользователем")
        graceful_stop("keyboard")
    except SystemExit:
        raise
    except Exception as e:
        log(f"💥 Crash: {e}")
        import traceback
        traceback.print_exc()
        emit("farm.crash", error=str(e)[:200])
        save_state()
        time.sleep(60)
