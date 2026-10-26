#!/usr/bin/env python3
"""
🚜 Farm Server v0.15
- /ws                      телефоны (hello, heartbeat, events, task, result)
- /client/manifest|file    раздача клиента (sha256)
- /bootstrap.py            установщик для телефонов
- /api/devices|send|broadcast|results|update
- /api/devices/{id} (DELETE) 🗑 удалить устройство (v0.13)
- /api/devices/{id}/cycle  🔁 НОВЫЙ ЦИКЛ на одном устройстве (v0.14)
- /api/devices/{id}/rescue 🚑 СПАСЕНИЕ сломавшегося телефона (v0.15):
                           убить петлю регы → фарм ⏹ → куки из пула сервера →
                           farm ▶ (если куки починились). Офлайн — отложится (⏳).
- /api/events              события фарма из SQLite (этап 2)
- /api/groups              группы устройств (этап 4) + send в группу
- /api/pool                🍪 пул кук на сервере (добавить/удалить/бронь)
- /api/schedule            ⏰ расписание: сбор по времени МСК (HOLD-режим)
- /api/pending             ⏳ отложенные команды (посмотреть/снять)
- /                        ЕДИНАЯ ПАНЕЛЬ (dashboard.html v1.6) — всё на одной странице,
                           без отдельных меню: главные кнопки + устройства + расписание
                           + пул кук + группы + события. Других адресов (типа :3000) НЕТ.

v0.17 — «ПРОКСИ: вставил блок из бота → вся сеть телефона через SOCKS5» (хозяин):
  • 🌐 ПУЛ ПРОКСИ: POST /api/proxy/add — парсер блока продавца (socks5://login:pass@ip:port,
    ip:порт + логин/пароль строками, дата окончания дд.мм.гг или «6д», комментарий «Shrd»).
    GET /api/proxy (список + кто на каком сидит), /api/proxy/delete, /api/proxy/clear,
    /api/proxy/distribute — раздать свободные телефонам без прокси (1 телефон = 1 прокси).
  • 🌐 ПРИВЯЗКА: POST /api/devices/{id}/proxy {"proxy_id": N|null} — назначить/снять.
    Онлайн-телефону — сразу, офлайн — ⏳ отложенная. Прокси, занятый другим
    телефоном, переезжает: старому уходит proxy.set null.
  • 🌐 КЛИЕНТ (proxy.set + proxy_fwd.py): поднимает локальный прозрачный
    форвардер (SO_ORIGINAL_DST → SOCKS5 с авторизацией) и заворачивает ВЕСЬ
    TCP-трафик телефона через iptables → «вся сеть через прокси». Исключения:
    сам прокси-сервер, сервер фермы, локальные сети (иначе потеряем телефон).
    UDP 443/80 режется (REJECT) — чтобы QUIC не утекал мимо прокси.
    Статус летит в heartbeat (info.proxy) → панель. При hello сервер
    синхронизирует привязку (как rega.switch).

v0.16 — «БАЙПАС ТОЛЬКО ЕСЛИ КЛЮЧУ БОЛЬШЕ 24ч» (хозяин, уточнение правила):
  • 🔓 Порог «правила хозяина» поднят с 23ч до 24ч на ВСЕХ уровнях:
    сервер (_BYPASS_MIN_KEY_AGE_H), клиент (BYPASS_MIN_KEY_AGE_H),
    фарм-сервис (BYPASS_MIN_KEY_AGE_H) и панель (подсказка 🔓/FORCE).
    Свежий ключ (<24ч) → bypass.run НЕ отправляется/отклоняется;
    ключа не было вовсе (None) → байпас ДОЛЖЕН пройти; force:true по-прежнему
    обходит правило (явное желание владельца).

v0.15 — «ТЕЛЕФОНЫ ЛОМАЮТСЯ: кнопка остановки петли + байпас только по ключу >23ч» (хозяин):
  • 🚑 ПОСТ /api/devices/{id}/rescue — телефон зациклился (rega.attempt ok=false →
    rega.stray убивает клоны → farm.restart их оживает → по кругу часами).
    Клиентская задача rescue.run делает ровно то, что просил хозяин:
    СТОП петли (убить регу + фарм ⏹ + закрыть ВСЕ роблоксы) →
    ВЗЯТЬ КУКИ ЕСЛИ НЕТ (rega check: пустые/мёртвые сессии заменяются ИЗ ПУЛА
    сервера, БЕЗ регистрации новых акков) → ФАРМ (farm ▶, только если куки
    починились ПОЛНОСТЬЮ — иначе фарм остаётся стоять, чтобы петля не вернулась).
    Офлайн-телефону команда откладывается (⏳) и вручается при подключении.
    Отложенные rega.start у устройства снимаются — петля не вернётся из очереди.
  • 🔓 БАЙПАС ТОЛЬКО ЕСЛИ КЛЮЧУ >23ч: сервер (orchestrate_new_cycle) и клиент
    (bypass.run / фарм-сервис) проверяют возраст ключа Дельты (last_key_time
    из farm_state.json): свежий (<23ч) → bypass.run НЕ отправляется/отклоняется
    («ключ свежий — байпас не нужен»). Если ключа не было вовсе — байпас ДОЛЖЕН
    пройти (иначе фарм без ключа). Ручная кнопка 🔓 в панели предложит FORCE.
  • force:true в bypass.run — явное принуждение владельцем (мимо правила 23ч).

v0.12 — «ВСЁ ПУСТЬ БУДЕТ НА :55019 БЕЗ ОТДЕЛЬНЫХ МЕНЮ» (хозяин):
  • 🖥 dashboard.html переписан в ЕДИНУЮ панель v1.2: главные кнопки
    (СБОР/НОВЫЙ ЦИКЛ/СТОП ФАРМ ВСЕМ/РЕГА СЕЙЧАС/тумблер регы) прямо сверху,
    ниже — устройства, расписание, пул кук, группы, события, журнал.
    Баннер «иди на :3000» УДАЛЕН — Next.js-панель на :3000 сквозь portmap-туннель
    всё равно недостижима (проброшен только порт 8000), из-за этого и было
    «кнопки не работают»: хозяин открывал дашборд-заглушку.
  • 🖥 GET / отдаёт панель с Cache-Control: no-store — после обновления кода
    браузер больше не показывает старую версию из кэша.
  • 📡 /api/schedule отдаёт harvest_running (индикатор HOLD-сбора в панели).

v0.14 — «НОВЫЙ ЦИКЛ: АККИ ЗАРЕГАЛО, А ФАРМ/БАЙПАС НЕ ПРОИСХОДИТ» (хозяин):
  • 🐛 КОРЕНЬ БАГА: после регы фарм поднимал клиентский watchdog, но сервис rega
    пишет реарм (farm=running) ПРЯМО В services_state.json, а ProcessManager
    клиента держал desired В ПАМЯТИ и файл перечитывал только при рестарте —
    реарм игнорировался, фарм не поднимался никогда. Фикс в клиенте (PM v0.26):
    watchdog перечитывает desired с диска каждый цикл.
  • 🔁 НОВЫЙ ЦИКЛ больше НЕ надеется на watchdog: сервер сам ждёт rega.done
    (до 4ч) и ЯВНО шлёт farm ▶ + 🔓 bypass.run — свежий ключ + фарм на новых акках.
  • 🛡 Тумблер «Рега акков» РЕШАЕТ: rega_enabled=false → НОВЫЙ ЦИКЛ ПРОПУСКАЕТ
    регистрацию и сразу фарм+байпас (акки с лутом не трогаются). Раньше цикл
    ВСЕГДА принудительно включал регу (cfg["rega_enabled"]=True) — хозяин:
    «я акки зарегал и не хочу новые создавать».
  • 🔁 НОВЫЙ POST /api/devices/{device_id}/cycle — «НОВЫЙ ЦИКЛ» на ОДНОМ
    устройстве (кнопка «🔁 Цикл» в строке телефона): подключил новый телефон —
    запусти цикл только ему. Панель v1.4.
  • ⏳ clear_pending(...) умеет снимать отложенные стопы ТОЛЬКО у одного
    устройства (кнопка на одном телефоне не отменяет стопы остальных).

v0.13 — «КНОПКА УДАЛИТЬ УСТРОЙСТВО + КЛИЕНТ НЕ НАЗНАЧАЕТ СЕБЕ ЗАДАЧИ» (хозяин):
  • 🗑 DELETE /api/devices/{device_id} — удалить устройство из панели:
    known_devices.json + его отложенные команды (+ сразу выпадает из списка,
    если был онлайн). Если клиент на телефоне жив — телефон появится снова
    при следующем hello (чтобы убрать НАВСЕГДА — farm_stop.sh на телефоне).
  • 🚫 клиент (services/farm) v0.25: УДАЛЁН авто-байпас по кулдауну 24ч
    (жалоба: «в 20 мин он начал делать байпас, хотя я всё остановил»).
    Байпас теперь ТОЛЬКО по задаче bypass.run (кнопка 🔓 в панели).
    Клиент больше НИКОГДА не назначает себе задачи сам.

v0.11 — «СТОП ФАРМ ВСЕМ НЕ РАБОТАЕТ / КНОПКИ ДЛЯ ВСЕХ НИЧЕГО НЕ ДЕЛАЮТ» (хозяин):
  • ⏳ ГЛАВНОЕ: команды «для всех» (Стоп фарм всем, тумблер регы) уходили ТОЛЬКО
    онлайн-телефонам. Если телефоны спали/офлайн — команда терялась НАВСЕГДА:
    фарм продолжал крутиться, рега — регистрировать. Теперь критические команды
    ОТКЛАДЫВАЮТСЯ (pending_commands.json, TTL 12ч) и вручаются телефону при
    следующем hello — «Стоп фарм всем» ДОГОНЯЕТ даже спящий телефон.
  • ⏳ известные device_id сохраняются (known_devices.json) — переживает рестарт
    сервера; в /api/devices офлайн-известные телефоны видны с пометкой pending;
  • ⏳ «Сбор сейчас» / «НОВЫЙ ЦИКЛ» / «Рега сейчас» снимают отложенные стопы —
    новое намерение хозяина важнее старого; в панели кнопка «Снять отложенные»;
  • 📡 честный broadcast: в ответе delivered/stale — видно, чья связь уже тухлая;
  • 📡 sender-фикс: мёртвый сокет при отправке ЧЕСТНО убирается из devices
    (раньше задачи молча утекали в пустоту с ответом «sent=N»).
v0.10 — ПАНЕЛЬ ЛАГАЛА / КНОПКИ «НЕ РАБОТАЮТ» (жалоба хозяина):
  • /client/manifest СИНХРОННО хешировал ВСЕ файлы клиента (включая info/ и
    logs/) прямо в event loop — на время хеширования СЕРВЕР НЕ ОТВЕЧАЛ НИ НА
    ЧТО (ни панель, ни телефоны) → «кнопки очень долго отвечают». Теперь
    скан идёт в отдельном потоке (asyncio.to_thread), а рантайм-папки
    info/ и logs/ ИСКЛЮЧЕНЫ из манифеста (попутный фикс: update больше НЕ
    заливает серверные client.pid/pids/*.json на телефоны и не перетирает
    их состояние);
  • панель v1.0: тост «отправлено» вылетает СРАЗУ, результат телефона
    догоняет тостом/в журнал — кнопки больше не «висят» 30–60с.
v0.8 — НОВЫЙ ЦИКЛ (по просьбе хозяина, «сделай пока что просто»):
  • 🗑 АРХИВ УБРАН: отработанные куки УДАЛЯЮТСЯ, а не складываются в архив;
    старые записи из архива возвращены в пул (миграция при старте);
  • 🌾 СБОР = HOLD: harvest.start ставит окно БЕЗ СРОКА — фармеры заходят
    в приватки с treid.lua и СИДЯТ там, пока хозяин не нажмёт «НОВЫЙ ЦИКЛ»;
    никаких «2 пачек по 20 мин» и авто-выхода больше нет;
  • 🔁 POST /api/cycle/new «НОВЫЙ ЦИКЛ» — ЕДИНСТВЕННЫЙ способ завершить цикл:
    рега включается (тумблер ON на сервере и телефонах) → окно сбора снято →
    фарм ⏹ → rega.start → рега сама поднимет фарм (ставится на фарм);
  • ⏹ POST /api/farm/stop «Стоп фарм всем» — окно сбора снято + farm ⏹ на всех;
  • 🆕 автрега по расписанию УДАЛЕНА: рега запускается ТОЛЬКО кнопкой
    «НОВЫЙ ЦИКЛ» (или «Рега сейчас» при включённом тумблере).
- v0.15: /api/devices/{id}/send, /api/broadcast, /api/groups/{name}/send —
          type:"task" ставится АВТОМАТИЧЕСКИ (клиент отвечает только на type=task)
- v0.7: 🛡 kill-switch регы акков (история):
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
from urllib.parse import quote

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


# ---------- ⏳ ОТЛОЖЕННЫЕ КРИТИЧЕСКИЕ КОМАНДЫ (v0.11) ----------
# ЖАЛОБА ХОЗЯИНА: «нажал Стоп фарм всем — ничего не происходит». Причина:
# телефоны в этот момент спали/были офлайн — команда уходит только онлайн,
# офлайн-телефон получит её НИКОГДА (фарм продолжит крутиться).
# Теперь критические команды (стоп фарма, окно сбора снять, рега-switch)
# ставятся в персистентную очередь и ВРУЧАЮТСЯ телефону при следующем hello.
# «Сбор сейчас» / «НОВЫЙ ЦИКЛ» / «Рега сейчас» снимают отложенные стопы —
# новое намерение хозяина всегда важнее старого.

PENDING_FILE = BASE_DIR / "pending_commands.json"
KNOWN_DEVICES_FILE = BASE_DIR / "known_devices.json"
PENDING_TTL = 12 * 3600          # отложенная команда живёт 12ч
PENDING_LOCK = threading.Lock()


def load_json_file(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json_file(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def remember_device(did: str):
    """Известные device_id (переживает рестарт сервера) — по ним откладываем
    команды для офлайн-телефонов."""
    if not did or did.startswith("anon_"):
        return
    with PENDING_LOCK:
        known = load_json_file(KNOWN_DEVICES_FILE, [])
        if did not in known:
            known.append(did)
            save_json_file(KNOWN_DEVICES_FILE, known[-300:])


def known_devices() -> list:
    return load_json_file(KNOWN_DEVICES_FILE, [])


def queue_pending(dids: list, task: str, payload: dict):
    """Отложить команду для устройств, которые сейчас офлайн."""
    with PENDING_LOCK:
        pend = load_json_file(PENDING_FILE, {})
        cut = now() - PENDING_TTL
        for did in dids:
            lst = [e for e in pend.get(did, []) if e.get("ts", 0) > cut]
            lst.append({"task": task, "payload": payload or {}, "ts": now()})
            pend[did] = lst
        save_json_file(PENDING_FILE, pend)


def pop_pending(did: str) -> list:
    """Забрать все отложенные команды устройства (при hello)."""
    with PENDING_LOCK:
        pend = load_json_file(PENDING_FILE, {})
        out = pend.pop(did, [])
        if out:
            save_json_file(PENDING_FILE, pend)
    return [e for e in out if e.get("ts", 0) > now() - PENDING_TTL]


def clear_pending(task_names: set | None = None, dids: list | None = None):
    """Снять отложенные команды (полностью или по типу) — при новом
    намерении хозяина (Сбор/Новый цикл/Рега).
    🆕 v0.14: dids — сузить на конкретные устройства (кнопка «🔁 Цикл»
    на одном телефоне не должна снимать отложенные стопы у остальных)."""
    with PENDING_LOCK:
        pend = load_json_file(PENDING_FILE, {})
        if not pend:
            return
        if task_names is None:
            if dids is None:
                save_json_file(PENDING_FILE, {})
                return
            for did in dids:
                pend.pop(did, None)
            save_json_file(PENDING_FILE, pend)
            return
        changed = False
        for did in list(pend):
            if dids is not None and did not in dids:
                continue
            kept = [e for e in pend[did] if e.get("task") not in task_names]
            if len(kept) != len(pend[did]):
                changed = True
            if kept:
                pend[did] = kept
            else:
                pend.pop(did)
        if changed:
            save_json_file(PENDING_FILE, pend)


def pending_summary() -> dict:
    """Сколько у каждого устройства отложенных команд (для панели)."""
    pend = load_json_file(PENDING_FILE, {})
    cut = now() - PENDING_TTL
    out = {}
    for did, lst in pend.items():
        live = [e for e in lst if e.get("ts", 0) > cut]
        if live:
            out[did] = [e.get("task") for e in live]
    return out


# ---------- SQLite (этапы 2+4) ----------

DB_PATH = BASE_DIR / "farm.db"
DB_LOCK = threading.Lock()


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # 🗑 v0.8: архив упразднён — всё, что лежало в архиве, возвращаем в пул
    try:
        conn.execute("UPDATE pool SET status='pool', claimed_by=NULL, claimed_ts=NULL "
                     "WHERE status='archive'")
        conn.commit()
    except Exception:
        pass
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
    # 🌐 v0.17: пул прокси + привязка прокси→телефон
    conn.execute("""CREATE TABLE IF NOT EXISTS proxies(
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme     TEXT DEFAULT 'socks5',   -- socks5 | http
        host       TEXT NOT NULL,
        port       INTEGER NOT NULL,
        login      TEXT DEFAULT '',
        password   TEXT DEFAULT '',
        expires_ts REAL,                    -- когда кончается аренда (NULL = неизвестно)
        comment    TEXT DEFAULT '',         -- «Shrd» из блока бота
        raw        TEXT DEFAULT '',         -- исходный текст блока (для отладки)
        added_ts   REAL,
        source     TEXT DEFAULT '')""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_proxy_uniq
                    ON proxies(host, port, login)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS proxy_assign(
        device_id   TEXT PRIMARY KEY,       -- один телефон = один прокси
        proxy_id    INTEGER,                -- NULL = прокси снят
        assigned_ts REAL)""")
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

# 🆑 v0.10: рантайм-папки НЕ раздаём как клиент: update на телефоне копирует
# ВСЁ из манифеста поверх своего состояния — серверные client.pid / info/pids/
# перетирали рабочие файлы телефона. logs/ к клиенту не относятся вообще.
CLIENT_SKIP_DIRS = {"__pycache__", "info", "logs"}
CLIENT_MAX_FILE = 30 * 1024 * 1024   # >30МБ в клиенте кода не бывает — не хешируем


def scan_client_dir() -> list:
    files = []
    if not CLIENT_DIR.exists():
        return files
    for p in sorted(CLIENT_DIR.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(CLIENT_DIR).parts
        if any(part in CLIENT_SKIP_DIRS for part in parts[:-1]):
            continue
        try:
            size = p.stat().st_size
            if size > CLIENT_MAX_FILE:
                continue
            files.append({"path": p.relative_to(CLIENT_DIR).as_posix(),
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                          "size": size})
        except OSError:
            continue
    return files


async def scan_client_dir_async() -> list:
    """🆑 v0.10: хеширование может занять секунды (много файлов) — раньше оно
    шло ПРЯМО в event loop и блокировало ВСЕ запросы (панель, телефоны).
    Теперь в отдельном потоке."""
    return await asyncio.to_thread(scan_client_dir)


def safe_client_path(rel: str) -> Path | None:
    if not rel or ".." in Path(rel).parts:
        return None
    p = (CLIENT_DIR / rel).resolve()
    if not str(p).startswith(str(CLIENT_DIR.resolve())):
        return None
    return p


@app.get("/client/manifest")
async def client_manifest():
    return {"files": await scan_client_dir_async(), "server_time": now()}


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
        # 🆑 v0.11: мёртвый сокет больше не «проглатывает» задачи молча —
        # при ошибке отправки устройство ЧЕСТНО убирается из devices,
        # чтобы «команды для всех» не улетали в пустоту с ответом «sent=N»
        try:
            while True:
                msg = await queue.get()
                await ws.send_text(json.dumps(msg))
        except Exception:
            cur = devices.get(device_id or "")
            if cur and cur.get("queue") is queue:
                devices.pop(device_id, None)
                log(f"[-] {device_id}: сокет мёртв при отправке → удалён из devices")

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
                remember_device(device_id)   # ⏳ v0.11: знаем id даже после рестарта сервера
                if sender_task is None:
                    sender_task = asyncio.create_task(sender())
                log(f"[+] {device_id} connected ({len(devices)} online)")
                await queue.put({"type": "welcome", "server_time": now(), "online": len(devices)})
                # ⏳ v0.11: вручаем отложенные команды («Стоп фарм всем», нажатый,
                # пока телефон был офлайн/спал — теперь он НЕ потерян навсегда)
                try:
                    pend = pop_pending(device_id)
                    for cmd in pend:
                        await queue.put({
                            "type": "task", "task": cmd.get("task"),
                            "payload": cmd.get("payload") or {},
                            "task_id": f"pend_{secrets.token_hex(3)}"})
                    if pend:
                        log(f"[⏳] {device_id}: вручены отложенные команды: "
                            f"{[c.get('task') for c in pend]}")
                except Exception as e:
                    log(f"[!] pending deliver {device_id}: {e}")
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
                # 🌐 v0.17: синхронизация прокси при hello — телефон догоняет свою
                # привязку (после рестарта сервера / долгого сна телефона).
                # Если телефон уже сообщает ровно тот же proxy_id — не дёргаем.
                try:
                    apid, aprow = db_proxy_assignment(device_id)
                    cur = (msg.get("info") or {}).get("proxy") or {}
                    if (cur.get("proxy_id") or None) != (apid or None) or \
                            (apid is None and cur.get("enabled")):
                        await queue.put({
                            "type": "task", "task": "proxy.set",
                            "payload": {"proxy": proxy_url(aprow) if aprow else None,
                                        "proxy_id": apid,
                                        "source": "server-hello-sync"},
                            "task_id": f"proxysw_{secrets.token_hex(3)}"})
                        log(f"[🌐] {device_id}: hello-sync proxy.set "
                            f"({aprow and (str(aprow['host']) + ':' + str(aprow['port'])) or 'выключить'})")
                except Exception as e:
                    log(f"[!] proxy sync {device_id}: {e}")

            elif t == "heartbeat":
                d = devices.get(device_id)
                if d:
                    d["last_seen"] = now()
                    if "battery" in msg:
                        d["info"]["battery"] = msg["battery"]
                    if "farm" in msg:
                        d["info"]["farm"] = msg["farm"]   # last_key_time → 🔑 дашборд
                    if "proxy" in msg:
                        d["info"]["proxy"] = msg["proxy"]  # 🌐 v0.17: статус прокси → панель
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
    pend = pending_summary()   # ⏳ v0.11: какие команды ждут офлайн-телефоны
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
            "pending": pend.get(did, []),
        })
    known = known_devices()
    for did in known:          # офлайн-известные — с их отложенными командами
        if did in devices:
            continue
        out.append({
            "device_id": did, "online": False, "last_seen_sec": None,
            "client_version": None, "info": {}, "uptime_sec": None,
            "groups": gmap.get(did, []), "pending": pend.get(did, []),
        })
    return {"count": len(out), "devices": out,
            "pending_total": sum(len(v) for v in pend.values())}


@app.get("/api/pending")
async def api_pending_get():
    """⏳ v0.11: какие критические команды ждут офлайн-телефоны."""
    return {"pending": pending_summary(), "known_devices": known_devices()}


@app.delete("/api/pending")
async def api_pending_clear():
    """⏳ кнопка «Снять отложенные команды» — если хозяин передумал."""
    clear_pending(None)
    log("[⏳] Отложенные команды сняты (кнопка панели)")
    return {"ok": True, "note": "отложенные команды сняты"}


@app.delete("/api/devices/{device_id}")
async def api_device_delete(device_id: str):
    """🗑 v0.13: УДАЛИТЬ УСТРОЙСТВО из панели.
    Убирает из known_devices.json (переживает рестарт сервера) и снимает его
    отложенные команды; если был онлайн — сразу выпадает из списка.
    ⚠️ Если клиент на телефоне жив — при следующем hello телефон появится
    СНОВА (сам переподключается). Убрать навсегда — farm_stop.sh на телефоне."""
    if not device_id or device_id.startswith("anon_"):
        raise HTTPException(400, "такое устройство удалить нельзя")
    removed_known = False
    removed_pending = 0
    with PENDING_LOCK:
        known = load_json_file(KNOWN_DEVICES_FILE, [])
        if device_id in known:
            known.remove(device_id)
            save_json_file(KNOWN_DEVICES_FILE, known)
            removed_known = True
        pend = load_json_file(PENDING_FILE, {})
        if device_id in pend:
            removed_pending = len(pend.pop(device_id))
            save_json_file(PENDING_FILE, pend)
    was_online = device_id in devices
    if was_online:
        devices.pop(device_id, None)   # онлайн → сразу исчезает из списка;
        # его ws-обработчик завершится сам (очередь отвязана), hello вернёт телефон
    ok = removed_known or was_online or removed_pending > 0
    note = (f"удалено: known={'да' if removed_known else 'нет'}, "
            f"отложенных снято: {removed_pending}, был онлайн: {'да' if was_online else 'нет'}") \
        if ok else "устройство и так отсутствует в панели"
    log(f"[🗑] Удаление устройства {device_id}: {note}")
    return {"ok": ok, "device_id": device_id, "removed_known": removed_known,
            "removed_pending": removed_pending, "was_online": was_online, "note": note}


@app.post("/api/devices/{device_id}/cycle")
async def api_device_cycle(device_id: str):
    """🔁 НОВЫЙ ЦИКЛ на ОДНОМ устройстве (v0.14): например, подключил новый
    телефон — запусти цикл только ему, остальных не трогает.
    Правило то же, что у общего «НОВЫЙ ЦИКЛ»: рега включена → рега →
    farm ▶ + байпас; выключена → сразу farm ▶ + байпас.
    Устройство должно быть сейчас на связи (кнопка для только что подключённых)."""
    if device_id not in devices:
        raise HTTPException(400, f"{device_id} сейчас не на связи — подключи телефон и повтори")
    if device_id.startswith("anon_"):
        raise HTTPException(400, "анонимам цикл не нужен")
    if is_collector(device_id):
        raise HTTPException(400, "сборщику «НОВЫЙ ЦИКЛ» не нужен — он про фармеров")
    clear_pending({"harvest.stop", "service.stop farm"}, dids=[device_id])
    cfg = load_schedule()
    with_rega = bool(cfg.get("rega_enabled", False))
    if with_rega:
        # килл-свитч → ON именно этому телефону (идемпотентно)
        await send_task(device_id, "rega.switch", {"enabled": True, "source": "cycle.dev"})
    log(f"[🔁] НОВЫЙ ЦИКЛ на {device_id} (рега={'ВКЛ' if with_rega else 'ВЫКЛ'})")
    spawn_bg(orchestrate_new_cycle(farmers=[device_id], collectors=[],
                                   with_rega=with_rega, source="cycle.dev"))
    return {"ok": True, "device_id": device_id, "with_rega": with_rega,
            "note": (f"Цикл на {device_id}: окно сбора снято → farm ⏹ → рега → "
                     f"после rega.done farm ▶ + байпас" if with_rega else
                     f"Цикл на {device_id}: окно сбора снято → регистрация ПРОПУЩЕНА "
                     f"(рега выключена) → farm ▶ + байпас")}


@app.post("/api/devices/{device_id}/rescue")
async def api_device_rescue(device_id: str):
    """🚑 v0.15 СПАСЕНИЕ сломавшегося телефона (кнопка «🚑 Спас» в строке).
    Симптом (хозяин, 25.10): рега пытается зарегистрировать акки, попытки падают
    (rega.attempt ok=false), stray-сторож убивает клоны, монитор фарма их оживает
    — телефон крутит эту петлю ЧАСАМИ и сам не остановится.
    Клиентская задача rescue.run (v0.25) делает по цепочке хозяина:
      СТОП ПЕТЛИ (убить регу → фарм ⏹ → закрыть все роблоксы) →
      ВЗЯТЬ КУКИ ЕСЛИ НЕТ (rega check — замена пустых/мёртвых сессий ИЗ ПУЛА
      сервера, БЕЗ регистрации новых акков) → ФАРМ (farm ▶, если куки починились
      полностью; иначе фарм остаётся остановлен — петля не вернётся).
    У офлайн/спящего телефона команда ОТКЛАДЫВАЕТСЯ (⏳) и вручается при hello.
    Отложенные rega.start устройства снимаются — петля не вернётся из очереди."""
    known = device_id in devices or device_id in known_devices()
    if not known:
        raise HTTPException(404, f"{device_id} неизвестен (не онлайн и не в известных)")
    # петля не должна вернуться из отложенных: снимаем queued rega.start
    clear_pending({"rega.start"}, dids=[device_id])
    if device_id not in devices:
        queue_pending([device_id], "rescue.run", {"source": "rescue.deferred"})
        log(f"[🚑] {device_id}: офлайн — спасение ОТЛОЖЕНО, выполнит при подключении")
        return {"ok": True, "device_id": device_id, "deferred": True,
                "note": "🚑 телефон офлайн — спасение отложено (⏳) и выполнится "
                        "сразу при подключении: петля будет остановлена, куки "
                        "заменятся из пула, фарм встанет если куки починятся"}
    tid = await send_task(device_id, "rescue.run", {"source": "panel"})
    log(f"[🚑] {device_id}: СПАСЕНИЕ запущено (task {tid}) — стоп петли → "
        f"куки из пула → фарм")
    return {"ok": True, "device_id": device_id, "deferred": False, "task_id": tid,
            "note": "🚑 спасение запущено: убиваю петлю (рега+фарм+роблоксы) → "
                    "куки из пула (без регистрации!) → farm ▶ если куки живы. "
                    "Долгая операция (до ~20 мин) — результат в ответе задачи"}


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
    """🆑 v0.11 честный broadcast: задача уходит ВСЕМ записям в devices,
    но в ответе видно, кому реально доставлено (онлайн), а чья связь уже
    тухлая (stale >90с без heartbeat — вероятно, задача не дойдёт)."""
    sent, stale = [], []
    for did, d in list(devices.items()):
        task_id = f"t_{secrets.token_hex(4)}"
        msg = dict(body)
        msg["task_id"] = task_id
        msg.setdefault("type", "task")   # v0.15
        await d["queue"].put(msg)
        remember_result(task_id, "sent", did)
        sent.append(task_id)
        if not device_online(did):
            stale.append(did)
    return {"sent": len(sent), "task_ids": sent,
            "delivered": [did for did in devices if did not in stale],
            "stale": stale}


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
    # 🗑 v0.8: архива больше нет — только пул
    return {"pool": {"total": pool_total, "free": pool_total - busy, "busy": busy},
            "archive": {"total": 0}}


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
    """Отчёт телефона: used → 🗑 v0.8 УДАЛЯЕМ (архива больше нет),
    dead → удалить, released → снять бронь (не понадобились)."""
    with DB_LOCK:
        for c in used or []:
            DB.execute("DELETE FROM pool WHERE cookie=?", (c,))
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


def db_pool_clear() -> int:
    """🗑 Очистить ВЕСЬ пул разом: удаляются все куки, включая забронированные.
    Счётчик id сбрасывается в ноль (sqlite_sequence), чтобы список начинался с #1."""
    with DB_LOCK:
        n = DB.execute("SELECT COUNT(*) FROM pool").fetchone()[0]
        DB.execute("DELETE FROM pool")
        try:
            DB.execute("DELETE FROM sqlite_sequence WHERE name='pool'")
        except Exception:
            pass
        DB.commit()
    return n


def db_pool_move(ids: list, to: str) -> int:
    # 🗑 v0.8: архива нет — переносить можно только в пул (снять бронь)
    if to not in ("pool",):
        raise HTTPException(400, "архив упразднён (v0.8): to must be 'pool'")
    with DB_LOCK:
        n = 0
        for i in ids:
            DB.execute("UPDATE pool SET status='pool', claimed_by=NULL, claimed_ts=NULL WHERE id=?",
                       (int(i),))
            n += DB.execute("SELECT changes()").fetchone()[0]
        DB.commit()
    return n


@app.get("/api/pool")
async def api_pool_get():
    # 🗑 v0.8: архива больше нет — возвращаем только пул (archive: [] для совместимости)
    return {"counts": db_pool_counts(),
            "pool": db_pool_entries("pool"),
            "archive": []}


@app.post("/api/pool/add")
async def api_pool_add(body: dict):
    entries = parse_pool_text(body.get("text") or "")
    if not entries:
        raise HTTPException(400, "куки не распознаны (нужно nick:/pass:/.ROBLOSECURITY=... или токены построчно)")
    # 🗑 v0.8: параметр to=archive игнорируется — добавляем всегда в пул
    added = db_pool_add(entries, status="pool", source=body.get("source") or "dashboard")
    return {"ok": True, "added": added, "counts": db_pool_counts()}


@app.post("/api/pool/delete")
async def api_pool_delete(body: dict):
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "no ids")
    return {"ok": True, "deleted": db_pool_delete(ids)}


@app.post("/api/pool/clear")
async def api_pool_clear(body: dict):
    """🗑 Очистить весь пул разом (v0.13). Защита: только с confirm=true."""
    if not body.get("confirm"):
        raise HTTPException(400, "требуется confirm:true — удалит ВСЕ куки безвозвратно")
    return {"ok": True, "deleted": db_pool_clear()}


@app.post("/api/pool/move")
async def api_pool_move(body: dict):
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "no ids")
    return {"ok": True, "moved": db_pool_move(ids, body.get("to") or "archive")}


@app.post("/api/pool/claim")
async def api_pool_claim(body: dict):
    """Телефон бронирует куки: {"device_id","n","from":"pool"}
    🗑 v0.8: from=archive больше не даёт кук — архива нет."""
    did = str(body.get("device_id") or "")
    n = min(max(int(body.get("n") or 0), 0), 50)
    if not did or n <= 0:
        raise HTTPException(400, "need device_id and n")
    status = "pool"
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
# 🌐 ПРОКСИ (v0.17): вставил блок из бота → парсим → привязка к телефону.
# Телефон при proxy.set поднимает локальный прозрачный форвардер
# (SO_ORIGINAL_DST → SOCKS5 с авторизацией) и заворачивает ВЕСЬ TCP
# через iptables в него — «вся сеть работает через прокси».
# ============================================================

RE_PROXY_URL = re.compile(
    r'(socks5h?|socks4|https?)://([^:@\s/]+):([^@\s/]+)@([\w.\-]+):(\d+)',
    re.I)
RE_IPV4PORT = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})\b')
RE_DATE_EXP = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:[,\s]+(\d{1,2}):(\d{2}))?')
RE_DAYS_EXP = re.compile(r'\b(\d{1,3})\s*д(?:н|ней|ня)?\b')
_PROXY_HEADER_WORDS = {"данные", "дата", "окончания", "комментарий",
                       "https", "socks5", "socks4", "http", "https/", "/"}


def parse_proxy_text(text: str) -> list:
    """Парсер блока из бота-продавца прокси. Формат:
        Shrd
            95.164.110.189:9176
            V45FCw
            tmr9H6
            socks5://V45FCw:tmr9H6@95.164.110.189:9176
            HTTPs / SOCKS5
            02.11.26, 20:23
            6д
    Основной источник — строка socks5://login:pass@ip:port. Если её нет,
    фолбэк: IP:порт + две строки-токена сразу после (логин, пароль).
    Дата окончания: дд.мм.гг (приоритет) или «6д» (дней от сейчас).
    Возвращает список dict: scheme/host/port/login/password/expires_ts/comment."""
    text = text or ""
    entries = []
    matches = list(RE_PROXY_URL.finditer(text))
    # блок прокси = [конец предыдущего URL … начало следующего URL]:
    # комментарий ищем ДО строки socks5://…, дату окончания — ПОСЛЕ неё
    for i, m in enumerate(matches):
        blk_start = matches[i - 1].end() if i > 0 else 0
        blk_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = text[blk_start:m.start()]
        after = text[m.end():blk_end]
        scheme = "http" if m.group(1).lower() in ("http", "https") else "socks5"
        host, port = m.group(4), int(m.group(5))
        if not _valid_host_port(host, port):
            continue
        comment = _comment_from(before, m.group(2), m.group(3))
        entries.append({"scheme": scheme, "host": host, "port": port,
                        "login": m.group(2), "password": m.group(3),
                        "expires_ts": _expiry_in(after, 0), "comment": comment})
    if not entries:
        # --- фолбэк: блоки без строки socks5:// ---
        for m in RE_IPV4PORT.finditer(text):
            host, port = m.group(1), int(m.group(2))
            if not _valid_host_port(host, port):
                continue
            login, password = "", ""
            tail = text[m.end():m.end() + 200].splitlines()
            head = text[max(0, m.start() - 200):m.start()].splitlines()
            if head:
                # последний элемент может содержать начало ip-строки — обрезаем
                idx = head[-1].find(m.group(1))
                head[-1] = head[-1][:idx] if idx >= 0 else head[-1]
            def _toks(lines):
                out = []
                for ln in lines:
                    ln = ln.strip()
                    if re.fullmatch(r'[A-Za-z0-9_.\-]{3,40}', ln or "") and \
                            not RE_DATE_EXP.search(ln) and not RE_DAYS_EXP.search(ln):
                        out.append(ln)
                    if len(out) == 2:
                        break
                return out
            toks = _toks(tail[1:])                       # после ip (формат продавца)
            if len(toks) < 2:
                pre = []                                 # до ip: последние два в прямом порядке
                for ln in head:                          # (splitlines уже без хвостовой пустой)
                    ln = ln.strip()
                    if re.fullmatch(r'[A-Za-z0-9_.\-]{3,40}', ln or "") and \
                            not RE_DATE_EXP.search(ln) and not RE_DAYS_EXP.search(ln):
                        pre.append(ln)
                toks = pre[-2:]
            if len(toks) == 2:
                login, password = toks[0], toks[1]
            entries.append({"scheme": "socks5", "host": host, "port": port,
                            "login": login, "password": password,
                            "expires_ts": _expiry_in(text, m.end()), "comment": ""})
    return entries


def _comment_from(before: str, login: str, password: str) -> str:
    """Комментарий («Shrd») — последняя содержательная строка ПЕРЕД блоком данных.
    Учётку/пароль/ip/даты/заголовки пропускаем."""
    for ln in reversed([l.strip() for l in before.splitlines()]):
        if not ln:
            continue
        low = ln.lower()
        if any(w in low for w in _PROXY_HEADER_WORDS):
            continue
        if RE_IPV4PORT.search(ln) or RE_DATE_EXP.search(ln) or RE_DAYS_EXP.search(ln):
            continue
        if login and ln == login:
            continue
        if password and ln == password:
            continue
        if re.fullmatch(r'[A-Za-zА-Яа-я0-9_\- ]{1,40}', ln):
            return ln
        break
    return ""


def _valid_host_port(host: str, port: int) -> bool:
    if not (1 <= int(port) <= 65535):
        return False
    if host.count(".") == 3 and all(p.isdigit() and int(p) <= 255 for p in host.split(".")):
        return True
    return bool(re.fullmatch(r'[a-z0-9][a-z0-9.\-]{2,120}', host, re.I))


def _expiry_in(text: str, from_pos: int) -> float | None:
    """Дата окончания в тексте ПОСЛЕ позиции from_pos: дд.мм.гг[, чч:мм]
    (приоритет) или «Nд» (дней от сейчас). None = не указано."""
    window = text[from_pos:from_pos + 400]
    m = RE_DATE_EXP.search(window)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        hh = int(m.group(4) or 23)
        mm = int(m.group(5) or 59)
        try:
            dt = datetime(y, mo, d, hh, mm)
            return dt.timestamp()
        except ValueError:
            pass
    m = RE_DAYS_EXP.search(window)
    if m:
        return now() + int(m.group(1)) * 86400
    return None


def proxy_url(row: dict) -> str:
    """URL для телефона: socks5://login:pass@host:port (учётка url-энкодится)."""
    auth = ""
    if row.get("login"):
        auth = quote(str(row["login"]), safe="") + ":" + quote(str(row.get("password") or ""), safe="") + "@"
    return f"{row.get('scheme') or 'socks5'}://{auth}{row['host']}:{row['port']}"


def db_proxy_add(entries: list, source: str = "dashboard") -> int:
    added = 0
    with DB_LOCK:
        for e in entries:
            try:
                DB.execute(
                    "INSERT OR IGNORE INTO proxies(scheme,host,port,login,password,"
                    "expires_ts,comment,raw,added_ts,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (e.get("scheme") or "socks5", e["host"], int(e["port"]),
                     e.get("login") or "", e.get("password") or "",
                     e.get("expires_ts"), (e.get("comment") or "")[:60],
                     (e.get("raw") or "")[:2000], now(), source))
                added += DB.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
        DB.commit()
    return added


def db_proxy_list() -> list:
    with DB_LOCK:
        rows = DB.execute(
            "SELECT id,scheme,host,port,login,password,expires_ts,comment,added_ts "
            "FROM proxies ORDER BY id").fetchall()
        assigns = dict(DB.execute(
            "SELECT proxy_id, device_id FROM proxy_assign WHERE proxy_id IS NOT NULL").fetchall())
    return [{"id": r[0], "scheme": r[1], "host": r[2], "port": r[3],
             "login": r[4], "password": r[5], "expires_ts": r[6],
             "comment": r[7], "added_ts": r[8],
             "device_id": assigns.get(r[0])} for r in rows]


def db_proxy_get(pid: int) -> dict | None:
    with DB_LOCK:
        r = DB.execute(
            "SELECT id,scheme,host,port,login,password,expires_ts FROM proxies WHERE id=?",
            (pid,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "scheme": r[1], "host": r[2], "port": r[3],
            "login": r[4], "password": r[5], "expires_ts": r[6]}


def db_proxy_delete(ids: list) -> int:
    ids = [int(i) for i in ids]
    n = 0
    with DB_LOCK:
        q = ",".join("?" * len(ids))
        n = DB.execute(f"DELETE FROM proxies WHERE id IN ({q})", ids).rowcount
        DB.execute(f"DELETE FROM proxy_assign WHERE proxy_id IN ({q})", ids)
        DB.commit()
    return max(n, 0)


def db_proxy_clear() -> int:
    with DB_LOCK:
        n = DB.execute("DELETE FROM proxies").rowcount
        DB.execute("DELETE FROM proxy_assign")
        try:
            DB.execute("DELETE FROM sqlite_sequence WHERE name='proxies'")
        except Exception:
            pass
        DB.commit()
    return max(n, 0)


def db_proxy_assignment(device_id: str) -> tuple[int | None, dict | None]:
    """(proxy_id, proxy_row) текущей привязки телефона; (None, None) если нет."""
    with DB_LOCK:
        r = DB.execute("SELECT proxy_id FROM proxy_assign WHERE device_id=?",
                       (device_id,)).fetchone()
    if not r or r[0] is None:
        return None, None
    return r[0], db_proxy_get(r[0])


def db_proxy_assign(device_id: str, pid: int | None) -> list:
    """Поменять привязку телефона. Возвращает список device_id, у которых
    ОТНЯЛИ прокси (их надо уведомить proxy.set null)."""
    displaced = []
    with DB_LOCK:
        if pid is not None:
            prev = DB.execute("SELECT device_id FROM proxy_assign WHERE proxy_id=?",
                              (pid,)).fetchone()
            if prev and prev[0] != device_id:
                displaced.append(prev[0])
                DB.execute("DELETE FROM proxy_assign WHERE device_id=?", (prev[0],))
        DB.execute("INSERT INTO proxy_assign(device_id,proxy_id,assigned_ts) VALUES(?,?,?) "
                   "ON CONFLICT(device_id) DO UPDATE SET proxy_id=?, assigned_ts=?",
                   (device_id, pid, now(), pid, now()))
        DB.commit()
    return displaced


async def notify_proxy_change(device_id: str, pid: int | None, prow: dict | None):
    """Отправить телефону proxy.set (онлайн — сразу, офлайн — ⏳ в отложенные)."""
    payload = {"proxy": proxy_url(prow) if prow else None,
               "proxy_id": pid, "source": "panel"}
    d = devices.get(device_id)
    if d and d.get("ws"):
        await send_task(device_id, "proxy.set", payload)
        log(f"[🌐] {device_id}: proxy.set отправлен ({prow and (str(prow['host']) + ':' + str(prow['port'])) or 'выключить'})")
    else:
        queue_pending([device_id], "proxy.set", payload)
        log(f"[🌐] {device_id}: proxy.set отложен (офлайн)")


@app.get("/api/proxy")
async def api_proxy_get():
    return {"proxies": db_proxy_list(), "now": now()}


@app.post("/api/proxy/add")
async def api_proxy_add(body: dict):
    text = body.get("text") or ""
    entries = parse_proxy_text(text)
    for e in entries:
        e["raw"] = text[:2000]
    if not entries:
        raise HTTPException(400, "прокси не распознаны — нужен блок с socks5://логин:пароль@ip:порт "
                                 "(или IP:порт + логин/пароль строками)")
    added = db_proxy_add(entries, source=body.get("source") or "dashboard")
    return {"ok": True, "added": added,
            "parsed": len(entries),
            "note": "дубликаты (тот же ip:порт+логин) пропускаются" if added < len(entries) else ""}


@app.post("/api/proxy/delete")
async def api_proxy_delete(body: dict):
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "no ids")
    return {"ok": True, "deleted": db_proxy_delete(ids)}


@app.post("/api/proxy/clear")
async def api_proxy_clear(body: dict):
    if not body.get("confirm"):
        raise HTTPException(400, "требуется confirm:true — удалит ВСЕ прокси и привязки")
    n = db_proxy_clear()
    log(f"[🌐] пул прокси очищен ({n}) — телефонам уйдёт proxy.set null при hello")
    return {"ok": True, "deleted": n}


@app.post("/api/proxy/distribute")
async def api_proxy_distribute():
    """🔗 Раздать свободные прокси телефонам без привязки (онлайн — сразу,
    офлайн — ⏳). Ровно один прокси на телефон."""
    proxies = [p for p in db_proxy_list() if not p.get("device_id")]
    assigned_map = {p["device_id"] for p in db_proxy_list() if p.get("device_id")}
    targets = [did for did in list(devices.keys())
               if did not in assigned_map and not is_collector(did)]
    done = []
    for did in targets:
        if not proxies:
            break
        p = proxies.pop(0)
        db_proxy_assign(did, p["id"])
        await notify_proxy_change(did, p["id"], p)
        done.append({"device_id": did, "proxy_id": p["id"]})
    log(f"[🌐] раздал {len(done)} прокси из свободных")
    return {"ok": True, "assigned": done,
            "note": ("свободные прокси кончились" if not proxies and done else "")}


@app.post("/api/devices/{device_id}/proxy")
async def api_device_proxy(device_id: str, body: dict):
    """Привязать/снять прокси на телефоне: {"proxy_id": 12} или {"proxy_id": null}.
    Неизвестному телефону — 404 (как у rescue). Если прокси уже у другого —
    переезжает: старому телефону уйдёт proxy.set null."""
    known = device_id in devices or device_id in known_devices()
    if not known:
        raise HTTPException(404, f"no_such {device_id} неизвестен (не онлайн и не в известных)")
    pid = body.get("proxy_id")
    if pid is not None:
        try:
            pid = int(pid)
        except Exception:
            raise HTTPException(400, "proxy_id должен быть числом или null")
        prow = db_proxy_get(pid)
        if not prow:
            raise HTTPException(404, f"прокси #{pid} не найден")
    else:
        prow = None
    for other in db_proxy_assign(device_id, pid):
        await notify_proxy_change(other, None, None)
    await notify_proxy_change(device_id, pid, prow)
    return {"ok": True, "device_id": device_id, "proxy_id": pid,
            "note": (f"прокси #{pid} → {device_id}" if pid else f"прокси снят с {device_id}")}


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


_HARVEST_RUNNING = False   # 🌾 v0.8: True пока фармеры сидят в приватках (HOLD до «НОВЫЙ ЦИКЛ»)

# ⏱️ v0.14: паузы оркестрации вынесены в константы (тестируемость: E2E сжимает их)
_CYCLE_WAIT_HARVEST_S = 45        # выход фарма из сессии сбора (≤40с мониторинг)
_CYCLE_WAIT_STOP_S = 30           # остановка фарма перед регой
_CYCLE_REGA_POLL_S = 30           # как часто проверяем rega.done
_CYCLE_REGA_TIMEOUT_S = 4 * 3600  # максимум ждём окончания регы

# 🔓 v0.16: ПРАВИЛО ХОЗЯИНА — байпас ТОЛЬКО если ключу Дельты >24ч.
# Если ключа не было вовсе (farm_state.json пуст/нет last_key_time) — байпас
# ДОЛЖЕН пройти (фарм без ключа не работает).
_BYPASS_MIN_KEY_AGE_H = 24.0


def _key_age_h(did: str) -> float | None:
    """Возраст ключа Дельты на устройстве (часы) или None — ключа не было/неизвестно.
    Возраст приходит в heartbeat (farm_state.json: last_key_time)."""
    f = (devices.get(did) or {}).get("info", {}).get("farm") or {}
    try:
        kt = float(f.get("last_key_time") or 0)
    except Exception:
        return None
    if kt <= 0:
        return None
    return (now() - kt) / 3600


def _bypass_wanted(did: str) -> bool:
    """🔓 v0.16: слать ли bypass.run на устройство. False = ключу <24ч (свежий —
    байпас вхолостую не гоняем). None-возраст (ключа нет) → True."""
    age = _key_age_h(did)
    if age is None or age >= _BYPASS_MIN_KEY_AGE_H:
        return True
    log(f"[🔓] {did}: ключу {age:.1f}ч < {_BYPASS_MIN_KEY_AGE_H:.0f}ч — "
        f"bypass.run НЕ отправляю (правило хозяина: байпас только по ключу >24ч)")
    return False


async def _wait_rega_done(farmers: list, since_ts: float,
                          timeout_s: float = None, poll_s: float = None) -> list:
    """🆕 v0.14: ждём rega.done от фармеров (события летят из outbox клиента
    в таблицу events). Возвращает список ЗАКОНЧИВШИХ.
    Кто не закончил за timeout — не получает farm ▶/байпас от сервера:
    клиентский watchdog (v0.26 читает реарм rearm_farm с диска) поднимет
    фарм сам, когда рега реально закончит."""
    timeout_s = _CYCLE_REGA_TIMEOUT_S if timeout_s is None else timeout_s
    poll_s = _CYCLE_REGA_POLL_S if poll_s is None else poll_s
    pending = set(farmers)
    deadline = now() + timeout_s
    done_all: list = []
    while pending and now() < deadline:
        await asyncio.sleep(poll_s)
        for did in list(pending):
            try:
                r = DB.execute(
                    "SELECT 1 FROM events WHERE device_id=? AND type='rega.done' AND recv>? LIMIT 1",
                    (did, since_ts)).fetchone()
            except Exception:
                r = None
            if r:
                pending.discard(did)
                done_all.append(did)
                log(f"[🔁] ✅ {did}: рега закончила ({len(done_all)}/{len(farmers)})")
    if pending:
        log(f"[🔁] ⏳ рега не закончила за {int(timeout_s // 3600)}ч: "
            f"{', '.join(sorted(pending))} — фарм им поднимет клиентский watchdog "
            f"после реального завершения регы")
    return done_all


async def orchestrate_new_cycle(farmers: list = None, collectors: list = None,
                                with_rega: bool = None, source: str = "cycle.new"):
    """🔁 НОВЫЙ ЦИКЛ (v0.14) — единственный способ завершить HOLD-сбор.
    Работает для ВСЕХ фармеров (кнопка «НОВЫЙ ЦИКЛ») и для ОДНОГО устройства
    (кнопка «🔁 Цикл» в строке телефона, source="cycle.dev").

    1) окно сбора снято у участников (фарм выходит из сессии сбора ≤40с);
    2) ждём 45с;
    3) два пути по тумблеру «Рега акков» (rega_enabled):
       • ВКЛЮЧЕНА → farm ⏹ (чистый старт) → 30с → rega.start → ждём rega.done
         (до 4ч) → каждому закончившему: farm ▶ + 🔓 bypass.run (свежий ключ);
       • ВЫКЛЮЧЕНА → акки НЕ ТРОГАЕМ: сразу farm ▶ + 🔓 bypass.run
         («я акки зарегал и не хочу новые создавать» — хозяин, 25.10).
    Перезапуск фарма теперь ЯВНЫЙ с сервера (v0.8-v0.13 молча надеялись на
    клиентский watchdog, который реарм rearm_farm не видел → «акки зарегало,
    фарм/байпас не происходит»). Watchdog остаётся страховкой."""
    global _HARVEST_RUNNING
    farmers = farmers_online() if farmers is None else farmers
    collectors = collectors_online() if collectors is None else collectors
    if not farmers:
        log("[🔁] НОВЫЙ ЦИКЛ: нет фармеров — некому фармить/регать")
        return {"sent": [], "note": "нет фармеров"}
    if with_rega is None:
        with_rega = bool(load_schedule().get("rega_enabled", False))
    all_online_now = set(farmers_online()) | set(collectors_online())
    log(f"[🔁] НОВЫЙ ЦИКЛ ({source}, рега={'ВКЛ' if with_rega else 'ВЫКЛ'}): "
        f"фармеры={farmers}, сборщики={collectors}")
    log(f"[🔁] шаг 1/3: снимаю окно сбора у {len(farmers) + len(collectors)} устройств")
    for did in collectors + farmers:
        await send_task(did, "harvest.stop", {})
    # 🌾 HOLD-индикатор гасим, только если цикл накрывает ВСЕХ, кто собирал
    if set(farmers + collectors) >= all_online_now:
        _HARVEST_RUNNING = False
    await asyncio.sleep(_CYCLE_WAIT_HARVEST_S)   # фарм выходит из сессии сбора (≤40с мониторинг)

    if not with_rega:
        log("[🔁] шаг 2/3: рега ВЫКЛЮЧЕНА — регистрацию ПРОПУСКАЮ, акки не трогаю")
        started, bypassed = [], []
        for did in farmers:
            if await send_task(did, "service.start", {"name": "farm"}):
                started.append(did)
            if _bypass_wanted(did):                      # 🔓 v0.16: ключу ≥24ч?
                await send_task(did, "bypass.run", {"source": source})
                bypassed.append(did)
        log(f"[🔁] шаг 3/3: farm ▶ → {', '.join(started) or '—'}; 🔓 bypass.run → "
            f"{', '.join(bypassed) or '— (всем свежие ключи, байпас не нужен)'}")
        return {"with_rega": False, "farm_started": started, "bypassed": bypassed}

    st = load_sched_state()
    st["rega_pending"] = list(farmers)
    st["rega_started"] = now()
    st["last_rega"] = datetime.now(MSK).strftime("%Y-%m-%d")
    save_sched_state(st)
    log(f"[🔁] шаг 2/3: farm ⏹ на {len(farmers)}: {', '.join(farmers)} (чистый старт для регы)")
    for did in farmers:
        await send_task(did, "service.stop", {"name": "farm"})
    await asyncio.sleep(_CYCLE_WAIT_STOP_S)   # фарм успевает остановиться и закрыть роблоксы
    cfg = load_schedule()
    sent = []
    for did in farmers:
        tid = await send_task(did, "rega.start", {"target": cfg.get("rega_target", 5)})
        if tid:
            sent.append(did)
    log(f"[🔁] шаг 3/3: рега запущена на {len(sent)}: {', '.join(sent)} — жду rega.done (до 4ч)")
    done = await _wait_rega_done(sent, since_ts=st["rega_started"])
    bypassed = []
    if done:
        log(f"[🔁] рега закончила: {', '.join(done)} → farm ▶ + 🔓 bypass.run (ключу ≥24ч)")
        for did in done:
            await send_task(did, "service.start", {"name": "farm"})
            if _bypass_wanted(did):                      # 🔓 v0.16: ключу ≥24ч?
                await send_task(did, "bypass.run", {"source": source})
                bypassed.append(did)
        log(f"[🔁] ЦИКЛ ЗАВЕРШЁН: {', '.join(done)} — фарм на акках; "
            f"байпас: {', '.join(bypassed) or '— (ключи свежие)'}")
    return {"with_rega": True, "rega_sent": sent, "rega_done": done, "bypassed": bypassed}


async def harvest_flow() -> bool:
    """🌾 СБОР УРОЖАЯ v3 — HOLD-РЕЖИМ (v0.8, «сделай пока что просто»):
    всем фармерам и сборщикам ставится окно сбора БЕЗ СРОКА (hold):
    они заходят в приватки с treid.lua/collet.lua и СИДЯТ там (вылетевший
    клон возвращается в СВОЮ приватку), пока хозяин не нажмёт «НОВЫЙ ЦИКЛ»
    (/api/cycle/new) или «Сбор стоп». Никаких пачек и авто-выхода.
    Фарм, который был остановлен («Стоп фарм всем»), поднимается сам —
    иначе некому прочитать окно. День (last_harvest) помечается при
    реальном старте — «впустую» клик день не сжигает."""
    global _HARVEST_RUNNING
    cfg = load_schedule()
    place = cfg.get("harvest_place_id") or ""
    farmers = farmers_online()
    collectors = collectors_online()
    if not farmers and not collectors:
        log("[🌾] Сбор: нет устройств — день НЕ помечен, попробуем снова")
        return False
    st = load_sched_state()
    st["last_harvest"] = datetime.now(MSK).strftime("%Y-%m-%d")
    save_sched_state(st)
    _HARVEST_RUNNING = True
    log(f"[🌾] СБОР (HOLD — до кнопки «НОВЫЙ ЦИКЛ»): фармеры={farmers} | сборщики={collectors}")
    # 1) окно сбора (hold) — клиент пишет info/harvest_window.json без срока
    for did in collectors + farmers:
        await send_task(did, "harvest.start", {"hold": True, "minutes": 0, "place_id": place})
    # 2) фарм должен ЖИТЬ, чтобы увидеть окно (PM.start идемпотентен: «already running» — норм)
    for did in farmers:
        await send_task(did, "service.start", {"name": "farm"})
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
    log("[⏰] Планировщик запущен (сбор HOLD/проверка кук, время МСК; рега — ТОЛЬКО по «НОВЫЙ ЦИКЛ»)")
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

                # 🆕 v0.8: АВТОРЕГА ПО РАСПИСАНИЮ УДАЛЕНА — рега запускается
                # ТОЛЬКО кнопкой «НОВЫЙ ЦИКЛ» (/api/cycle/new) или «Рега сейчас».

                if (_hhmm_passed(now_msk, cfg.get("harvest_time", "20:00"))
                        and _within_catchup(now_msk, cfg.get("harvest_time", "20:00"))
                        and st.get("last_harvest") != today
                        and not _HARVEST_RUNNING):
                    spawn_bg(harvest_flow())

                if not st.get("rega_pending") and not _HARVEST_RUNNING:
                    # 🛡 во время HOLD-сбора проверку кук НЕ шлём (клиент и сам
                    # откажет — окно сбора активно); check перезапускает клоны
                    # и срывает трейд
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
            "harvest_running": _HARVEST_RUNNING,   # 🖥 v0.12: индикатор HOLD-сбора для панели
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
    clear_pending({"harvest.stop", "service.stop farm"})   # ⏳ новое намерение важнее старого стопа
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
    # ⏳ v0.11: офлайн/полуживые телефоны НЕ узнают о тумблере до hello — откладываем,
    # иначе «выключил регу, а телефон, включившийся позже, продолжит регать»
    online_set = set(sent)
    offline = [did for did in known_devices()
               if did not in online_set and did not in devices]
    offline += [did for did in devices
                if did not in online_set and not did.startswith("anon_")]
    offline = sorted(set(offline))
    if offline:
        queue_pending(offline, "rega.switch", {"enabled": enabled,
                                               "source": "deferred-switch"})
    log(f"[🛡] Рега акков {'ВКЛЮЧЕНА' if enabled else 'ОТКЛЮЧЕНА (безопасный режим)'} "
        f"— rega.switch отправлен: {sent or '—'}; отложен для офлайн: {offline or '—'}")
    note = ("рега ВКЛЮЧЕНА — телефоны снова регистрируют акки"
            if enabled else
            "🛡 рега ОТКЛЮЧЕНА — авторегистрация и замена кук остановлены, "
            "акки с лутом защищены")
    if offline:
        note += f"; ⏳ офлайн-телефоны ({len(offline)}) получат состояние при подключении"
    return {"ok": True, "rega_enabled": enabled, "sent": sent, "queued": offline,
            "note": note}


@app.post("/api/harvest/start")
async def api_harvest_now():
    """Кнопка «Сбор сейчас» — вне расписания. HOLD-режим: фармеры зайдут в
    приватки с treid.lua и будут сидеть там до кнопки «НОВЫЙ ЦИКЛ».
    last_harvest ставит сам harvest_flow при реальном старте — клик
    «впустую» не сжигает день"""
    farmers = farmers_online()
    collectors = collectors_online()
    if not farmers and not collectors:
        log("[🌾] Сбор сейчас: нет онлайн-устройств")
        return {"ok": False, "farmers": [], "collectors": [],
                "farmers_total": farmers_total(), "collectors_total": collectors_total(),
                "note": "нет онлайн-устройств — некому запускать сбор"}
    clear_pending({"harvest.stop", "service.stop farm"})   # ⏳ сбор стартует — старые стопы не нужны
    spawn_bg(harvest_flow())
    return {"ok": True, "farmers": farmers, "collectors": collectors,
            "note": "сбор запущен (HOLD): фармеры в приватках с treid.lua до кнопки «НОВЫЙ ЦИКЛ»"}


@app.post("/api/cycle/new")
async def api_cycle_new():
    """🔁 НОВЫЙ ЦИКЛ (v0.14): единственный выход из HOLD-сбора.
    Тумблер «Рега акков» РЕШАЕТ путь:
    • ВКЛ → рега новых акков → после rega.done farm ▶ + байпас;
    • ВЫК → регистрацию ПРОПУСКАЕМ, сразу farm ▶ + байпас (акки не трогаем).
    Раньше (v0.8-v0.13) цикл ВСЕГДА принудительно включал регу и после регы
    надеялся на клиентский watchdog, который реарм не видел → «акки зарегало,
    фарм/байпас не происходит» (жалоба хозяина 25.10)."""
    farmers = farmers_online()
    if not farmers:
        log("[🔁] НОВЫЙ ЦИКЛ: нет онлайн-фармеров")
        return {"ok": False, "farmers": [], "farmers_total": farmers_total(),
                "note": "нет онлайн-фармеров — некому запускать новый цикл"}
    clear_pending({"harvest.stop", "service.stop farm"})   # ⏳ новый цикл — старые стопы отменяются
    cfg = load_schedule()
    with_rega = bool(cfg.get("rega_enabled", False))
    sent_sw = []
    if with_rega:
        # килл-свитч → ON на всех онлайн-телефонах (идемпотентно: он уже ON).
        # Это НЕ «тихая авторега»: хозяин сам нажал «НОВЫЙ ЦИКЛ» при включённом тумблере.
        for did in list(devices.keys()):
            if did.startswith("anon_") or not device_online(did):
                continue
            if await send_task(did, "rega.switch", {"enabled": True,
                                                    "source": "cycle.new"}):
                sent_sw.append(did)
        log(f"[🔁] НОВЫЙ ЦИКЛ: рега включена (rega.switch → {sent_sw or '—'}); запускаю оркестрацию")
    else:
        log("[🔁] НОВЫЙ ЦИКЛ: рега ВЫКЛЮЧЕНА (rega_enabled=false) — "
            "регистрацию пропускаю, сразу фарм + байпас")
    spawn_bg(orchestrate_new_cycle(farmers=farmers, collectors=collectors_online(),
                                   with_rega=with_rega, source="cycle.new"))
    return {"ok": True, "farmers": farmers, "with_rega": with_rega, "rega_switch_sent": sent_sw,
            "note": ("НОВЫЙ ЦИКЛ: окно сбора снято → farm ⏹ → рега → после rega.done "
                     "farm ▶ + байпас" if with_rega else
                     "НОВЫЙ ЦИКЛ: окно сбора снято → регистрация ПРОПУЩЕНА (рега выключена) "
                     "→ farm ▶ + байпас на текущих акках")}


@app.post("/api/farm/stop")
async def api_farm_stop_all():
    """⏹ СТОП ФАРМ ВСЕМ (v0.8): окно сбора снято у всех + farm ⏹ у всех.
    ⏳ v0.11: телефоны, которые сейчас ОФЛАЙН/СПЯТ, раньше команду теряли
    навсегда («нажал — ничего не происходит»). Теперь стоп ОТКЛАДЫВАЕТСЯ
    для них и вручается при следующем подключении (hello), TTL 12ч.
    Отложенные стопы снимаются «Сбором сейчас»/«НОВЫМ ЦИКЛОМ»/«Регой сейчас»."""
    targets = [did for did in devices
               if device_online(did) and not did.startswith("anon_")]
    sent = []
    for did in targets:
        ok1 = await send_task(did, "harvest.stop", {})   # окно сбора снять (не вернётся в сбор)
        ok2 = await send_task(did, "service.stop", {"name": "farm"})
        if ok1 or ok2:
            sent.append(did)
    global _HARVEST_RUNNING
    _HARVEST_RUNNING = False
    # ⏳ отложить для известных, но сейчас офлайн/полуживых устройств
    online_set = set(targets)
    offline = [did for did in known_devices()
               if did not in online_set and did not in devices]
    offline += [did for did in devices
                if did not in online_set and not did.startswith("anon_")]
    offline = sorted(set(offline))
    if offline:
        queue_pending(offline, "harvest.stop", {})
        queue_pending(offline, "service.stop", {"name": "farm"})
    if not targets and not offline:
        return {"ok": False, "sent": [], "queued": [],
                "note": "нет известных устройств — панель их ещё не видела "
                        "(телефоны ни разу не подключались с момента первого запуска сервера)"}
    note = "фарм остановлен на всех онлайн, окно сбора снято (роблоксы закрыты)"
    if offline:
        note += (f"; ⏳ отложено для {len(offline)} офлайн: {', '.join(offline[:8])}"
                 f"{'…' if len(offline) > 8 else ''} — применится при их подключении")
    log(f"[⏹] СТОП ФАРМ ВСЕМ: окно снято + farm ⏹ → онлайн {sent}; "
        f"отложено {len(offline)}: {offline}")
    return {"ok": True, "sent": sent, "queued": offline, "note": note}


@app.post("/api/cookie/check")
async def api_cookie_check():
    farmers = farmers_online()
    for did in farmers:
        await send_task(did, "cookie.check", {})
    return {"ok": True, "sent": farmers}


# ---------- Дашборд ----------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """🖥 v0.12: ЕДИНАЯ панель (всё на одной странице, без отдельных меню).
    no-store — чтобы после git pull браузер не показал старую панель из кэша."""
    if not DASHBOARD_FILE.is_file():
        return HTMLResponse("<h1>dashboard.html не найден в ~/farm-server/</h1>", status_code=500)
    return HTMLResponse(DASHBOARD_FILE.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, must-revalidate"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
