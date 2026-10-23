#!/usr/bin/env python3
"""
📦 СЕРВИС СБОРЩИКА (services/collector/main.py) v1.0 — ОТПРАВНАЯ ТОЧКА ТРЕЙДА

Отдельный телефон-сборщик: его клоны (целевые акки, например forsellmm2x)
сидят в приватных серверах и АВТОМАТОМ ПРИНИМАЮТ трейды от фармеров
(treid.lua фармеров шлёт лут — collet.lua сборщика принимает).

Портирован из скрипта хозяина bank.py (Roblox Farm v16.6 FILE LICENSE INJECT
+ MULTI PRIVATE SERVER), адаптирован под систему:

- ✅ Запускается ТОЛЬКО через ProcessManager (service.start collector),
    stdout → logs/services/collector.log; phone device_id = collector-1/2/...
- ✅ Автоэкзекют Дельты = collet.lua (авто-приём трейдов + anti-AFK):
    качается с GitHub, кэш info/collector_collet.lua, фолбэк — зашитая loadstring.
- ✅ Приватные сервера — ТОЛЬКО из id.txt хозяина (32-симв. share-коды,
    кэш info/harvest_ids.txt — общий с фармом); клоны расходятся по кругу.
- ✅ Окно сбора пишет КЛИЕНТ (harvest.start/harvest.stop →
    info/harvest_window.json) — ТОТ ЖЕ файл, что читает фарм на фармерах:
    серверу не важно, кто на другом конце, протокол не менялся.
- ✅ Байпас — ПОЛНЫЙ v18.8: импортируем services/farm/main.py (тот же ZEN-ключ,
    9 попыток, ландшафт, license read-back, кулдаун 24ч в info/farm_state.json —
    на сборщике фарм-сервис не живёт, конфликта писателей нет).
    🔓 Кнопка «БАЙПАС» на дашборде работает и для сборщика: клиент ставит
    тот же флаг bypass_force.json, collector его съедает (фарм при живом
    collector клиент не стартует).
- ✅ Мониторинг окна: вылетевший клон возвращается НА СВОЙ приватный сервер
    (grace 90с на долёт через браузерный редирект, как у фарма).
- ✅ События → info/farm_events.jsonl (outbox клиента) — видны в 📅 дашборда:
    collector.start / collector.window / collector.window_end /
    collector.restart / collector.bypass.skipped.
- 🛡 СБОРЩИК НИЧЕГО НЕ УДАЛЯЕТ И НЕ ПЕРЕРЕГИСТРИРУЕТ: только принимает трейды.
    Куки/WebView не трогаются. treid.lua фармеров безопасен для акков сам по
    себе (ждёт цели, если сборщиков нет).

⚠️ На ФАРМЕРАХ этот сервис НЕ запускать: фарм и сборщик дерутся за роблоксов
и автоэкзекют. collector-телефон = клиент + сервис collector, всё.
"""
import os
import sys
import json
import time
import signal
from pathlib import Path
from datetime import datetime

# --- ~/farm (services/collector/main.py → parents[2]) ---
BASE = Path(__file__).resolve().parents[2]

COLLET_URL = "https://raw.githubusercontent.com/gleb228666999/test/refs/heads/main/collet.lua"
IDS_URL = "https://raw.githubusercontent.com/gleb228666999/test/refs/heads/main/id.txt"
COLLET_CACHE = BASE / "info" / "collector_collet.lua"
IDS_CACHE = BASE / "info" / "harvest_ids.txt"     # общий кэш с фармом
COLLET_FALLBACK = ("loadstring(game:HttpGet('https://raw.githubusercontent.com/"
                   "gleb228666999/test/refs/heads/main/collet.lua'))()")

HARVEST_WINDOW_FILE = BASE / "info" / "harvest_window.json"

WINDOW_POLL = 15        # сек между проверками окна/флага в простое
CHECK_INTERVAL = 30     # сек между проверками видимости во время окна
RELAUNCH_GRACE = 90     # сек grace на долёт в приватку (браузерный редирект)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================================
# 🔗 ИМПОРТ ФАРМА: полный байпас v18.8 + хелперы
# (farm/main.py не имеет побочных эффектов на импорте: main() только в __main__)
# ==========================================

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "farm_service_mod", str(BASE / "services" / "farm" / "main.py"))
farm = importlib.util.module_from_spec(_spec)
sys.modules["farm_service_mod"] = farm          # чтобы жило в глобальных
try:
    _spec.loader.exec_module(farm)
except Exception as e:
    log(f"💥 Не удалось загрузить services/farm/main.py: {e}")
    raise SystemExit(1)


# ==========================================
# 🌾 ОКНО СБОРА (тот же файл, что у фарма)
# ==========================================

def harvest_window():
    """Активное окно сбора или None (нет/истекло/снято)."""
    try:
        hw = json.loads(HARVEST_WINDOW_FILE.read_text())
        until = float(hw.get("until_ts") or 0)
        if time.time() >= until:
            return None
        return {"until_ts": until, "place_id": str(hw.get("place_id") or "")}
    except Exception:
        return None


def get_codes():
    """Share-коды приваток из id.txt (сеть → кэш)."""
    return farm.parse_share_codes(farm.fetch_text(IDS_URL, IDS_CACHE) or "")


def last_key_age():
    """Возраст ключа байпаса (farm_state.json пишет farm.run_bypass_cycle)."""
    try:
        v = json.loads((BASE / "info" / "farm_state.json").read_text())
        return time.time() - float(v.get("last_key_time") or 0)
    except Exception:
        return float("inf")


# ==========================================
# 🚀 ЗАПУСК ЦЕЛЕЙ (акков-приёмщиков) В ПРИВАТКИ
# ==========================================

def launch_targets(codes):
    """Клоны сборщика — по привяткам ПО КРУГУ (как в bank.py:
    share-ссылка в браузере → редирект в Roblox; фолбэк — deep link в плейс).
    Клонов нет → запускаем главный Roblox (Дельту) — у сборщика может не быть
    клонов, а приёмщик-акк может жить на главном пакете."""
    pkgs = farm.get_farm_packages()
    launch_map = {}
    if not pkgs:
        log("⚠️ Клонов нет — запускаю ГЛАВНЫЙ Roblox (Дельта) в приватку")
        pkgs = [farm.PACKAGE_MAIN]
    for i, pkg in enumerate(pkgs):
        code = codes[i % len(codes)] if codes else None
        if code:
            share = f"https://www.roblox.com/share?code={code}&type=Server"
            launch_map[pkg] = share
            log(f"🔗 [{i + 1}] {pkg} → приватка {code[:8]}…")
            ok, _, _ = farm.run_su(
                f"am start -a android.intent.action.VIEW -d '{share}' {pkg}", timeout=10)
            if not ok:
                log(f"   ⚠️ share-ссылка не сработала — фолбэк: deep link в плейс {farm.PLACE_ID}")
                farm.run_su(f"am start -a android.intent.action.VIEW "
                            f"-d 'roblox://experiences/start?placeId={farm.PLACE_ID}' {pkg}",
                            timeout=5)
                launch_map[pkg] = ""      # перезапуск — в плейс
        else:
            launch_map[pkg] = ""
            farm.run_su(f"am start -a android.intent.action.VIEW "
                        f"-d 'roblox://experiences/start?placeId={farm.PLACE_ID}' {pkg}",
                        timeout=5)
        time.sleep(2)
    log("   ⏳ Жду 5 сек на обработку share-ссылок браузером...")
    time.sleep(5)
    return pkgs, launch_map


# ==========================================
# 🌾 ОКНО СБОРА: главный цикл приёмника
# ==========================================

def run_window(hw):
    until = float(hw.get("until_ts") or 0)
    minutes = max(1, int((until - time.time()) // 60))
    codes = get_codes()
    log(f"📦 ОКНО СБОРА: {minutes} мин · приваток {len(codes) or 'нет (плейс)'}")
    farm.emit("collector.window", minutes=minutes, codes=len(codes))
    farm.kill_all_roblox()
    pkgs, launch_map = launch_targets(codes)
    last_launch = {p: time.time() for p in pkgs}     # grace на долёт

    while time.time() < until and not _stop["flag"]:
        time.sleep(min(CHECK_INTERVAL, max(1, until - time.time())))
        if _stop["flag"]:
            break
        if harvest_window() is None:
            # 🛑 окно снято досрочно (harvest.stop с дашборда / клиент удалил файл)
            log("🛑 Окно сбора снято досрочно (harvest.stop) — выхожу из окна")
            break

        # 🔓 кнопка байпаса — приоритетнее всего (флаг НЕ съедаем без живого акка)
        if farm.bypass_requested():
            try:
                ok_acc = farm.main_cookie_valid()
            except Exception:
                ok_acc = True
            if ok_acc and farm.consume_bypass_request() is not None:
                log("🔓 Байпас по кнопке ПРЯМО ВО ВРЕМЯ окна (сборщик)...")
                farm.kill_all_roblox()
                farm.run_bypass_cycle()
            else:
                log("🍪 Акк сборщика не жив — флаг байпаса сохранён, жду регу/починку")
                farm.emit("collector.bypass.skipped", reason="no_account")
                time.sleep(60)
            if time.time() >= until:
                break
            # вернуться в приватки: окно ещё живо
            farm.kill_all_roblox()
            pkgs, launch_map = launch_targets(codes)
            last_launch = {p: time.time() for p in pkgs}
            continue

        win_out, act_out = farm.get_visibility_snapshots()
        if win_out is None and act_out is None:
            log("⚠️ dumpsys недоступен — пропуск проверки")
            continue
        for pkg in pkgs:
            if farm.is_pkg_visible(pkg, win_out, act_out):
                continue
            if time.time() - last_launch.get(pkg, 0) < RELAUNCH_GRACE:
                continue        # ещё долетает в приватку
            log(f"⚠️ {pkg} не виден → перезапуск в свою приватку")
            farm.emit("collector.restart", pkg=pkg)
            farm.run_su(f"am force-stop {pkg}", timeout=5)
            time.sleep(15)
            link = launch_map.get(pkg)
            if link:
                ok, _, _ = farm.run_su(
                    f"am start -a android.intent.action.VIEW -d '{link}' {pkg}", timeout=10)
                if not ok:
                    farm.run_su(f"am start -a android.intent.action.VIEW "
                                f"-d 'roblox://experiences/start?placeId={farm.PLACE_ID}' {pkg}",
                                timeout=5)
            else:
                farm.run_su(f"am start -a android.intent.action.VIEW "
                            f"-d 'roblox://experiences/start?placeId={farm.PLACE_ID}' {pkg}",
                            timeout=5)
            last_launch[pkg] = time.time()

    farm.kill_all_roblox()
    farm.emit("collector.window_end")
    log("📦 Окно сбора закрыто — роблоксы убраны, жду следующего окна")


# ==========================================
# ⏱ ПЛАНОВЫЙ БАЙПАС (кулдаун 24ч)
# ==========================================

def maybe_scheduled_bypass():
    """Кулдаун истёк → полный байпас v18.8. Акка нет → ждём (фарм-гейт логика
    не нужна: у сборщика нет рега, просто ждём живой акк)."""
    if last_key_age() < farm.BYPASS_COOLDOWN:
        return
    try:
        ok_acc = farm.main_cookie_valid()
    except Exception:
        ok_acc = True
    if not ok_acc:
        log("🍪 Нет живого акка на главном Roblox — плановый байпас отложен (30 мин)")
        farm.emit("collector.bypass.skipped", reason="no_account")
        time.sleep(1800)
        return
    log("⏱ Кулдаун байпаса истёк — полный цикл v18.8 (Delta → реклама → ZEN → license)")
    farm.kill_all_roblox()
    farm.run_bypass_cycle()


# ==========================================
# 🛑 SIGTERM / ГЛАВНЫЙ ЦИКЛ
# ==========================================

_stop = {"flag": False}


def _sigterm(_s, _f):
    log("🛑 SIGTERM — останавливаю сборщика...")
    _stop["flag"] = True


def main():
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    log("📦 COLLECTOR SERVICE START v1.0 (сборщик: авто-приём трейдов, банк)")
    log(f"   su: {farm.SU_BIN}")
    log(f"   base: {BASE}")
    log(f"   ZEN-API: {'✅' if farm.ZEN_API_KEY else '❌'} | "
        f"байпас v18.8 ({farm.BYPASS_CLICK_RETRIES}+{farm.BYPASS_DBLCLICK_RETRIES} попыток, кулдаун 24ч)")

    # 📝 автоэкзекют Дельты = collet.lua (авто-приём трейдов + anti-AFK)
    lua = farm.fetch_text(COLLET_URL, COLLET_CACHE) or COLLET_FALLBACK
    if farm.create_delta_lua(lua):
        log("✅ Автоэкзекют Дельты = collet.lua готов")
    else:
        log("⚠️ Не удалось записать collet.lua (продолжаю — попробуем в следующем цикле)")

    codes = get_codes()
    log(f"🔗 Приватки из id.txt: {len(codes)} шт."
        if codes else "⚠️ id.txt недоступен — возьму при запуске окна (кэш/плейс)")

    farm.emit("collector.start", pid=os.getpid(), codes=len(codes))

    while not _stop["flag"]:
        try:
            # 🔓 байпас по кнопке (клиент не стартует фарм при живом collector)
            if farm.bypass_requested():
                try:
                    ok_acc = farm.main_cookie_valid()
                except Exception:
                    ok_acc = True
                if ok_acc and farm.consume_bypass_request() is not None:
                    log("🔓 Байпас по кнопке (сборщик): полный цикл v18.8")
                    farm.kill_all_roblox()
                    farm.run_bypass_cycle()
                else:
                    log("🍪 Акк не жив — флаг байпаса сохранён (не тратится)")
                    farm.emit("collector.bypass.skipped", reason="no_account")
                    time.sleep(60)
                continue

            # 🌾 окно сбора: сервер прислал harvest.start → клиент написал файл
            hw = harvest_window()
            if hw:
                try:
                    run_window(hw)
                except Exception as e:
                    log(f"💥 Окно упало: {e}")
                    farm.emit("collector.fail", error=str(e)[:200])
                    farm.kill_all_roblox()
                continue

            # ⏱ плановый байпас по кулдауну 24ч
            maybe_scheduled_bypass()
            if _stop["flag"]:
                break

            time.sleep(WINDOW_POLL)
        except Exception as e:
            log(f"💥 loop: {e}")
            time.sleep(30)

    # 🧹 чистый выход: телефон остаётся без роблоксов
    farm.kill_all_roblox()
    farm.emit("collector.stop")
    log("📦 Сборщик остановлен")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("🛑 Остановлено пользователем")
        farm.kill_all_roblox()
    except SystemExit:
        raise
    except Exception as e:
        log(f"💥 Crash: {e}")
        import traceback
        traceback.print_exc()
        farm.emit("collector.crash", error=str(e)[:200])
        time.sleep(60)
