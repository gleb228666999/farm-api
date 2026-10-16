#!/usr/bin/env python3
"""
🤖 Roblox Farm v16.2 (FILE LICENSE INJECT)
✅ ВСЕГДА перезаписывает /storage/emulated/0/Delta/Autoexecute/1.lua при запуске
✅ Прямой запрос к ZEN-API
✅ 24-часовой таймер байпаса
✅ Записывает ключ напрямую в файл license (без ввода через экран)
✅ 3 тапа по рекламе для получения ссылки
✅ ОБНОВЛЕНО: Во время БАЙПАСА запуск СРАЗУ в плейс (без главного меню)
✅ ОБНОВЛЕНО: Во время ФАРМЫ вход в меню убран, оставлено только ожидание 15 сек -> прямой запуск в плейс
✅ ОБНОВЛЕНО: com.roblox.client запускается ТОЛЬКО при байпасе, ферма его игнорирует
✅ ОБНОВЛЕНО: Мониторинг фермы каждые 30 сек — если окно не видно, пакет перезапускается
✅ ОБНОВЛЕНО: Если пакет вылетел, перед перезапуском тоже ожидание 15 сек
"""
import requests, time, subprocess, os, json, sys, re, urllib.parse
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

AD_BTN_X, AD_BTN_Y = 1000, 470

FORCE_BYPASS = False
DEBUG_MODE = True
BYPASS_COOLDOWN = 86400
MAX_RETRIES = 3
PACKAGE_MAIN = "com.roblox.client"
PLACE_ID = "142823291"
STATE_FILE = "farm_state.json"

state = {"last_key_time": 0.0}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def run_su(cmd, timeout=15):
    try:
        res = subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def tap(x, y):
    run_su(f"input tap {x} {y}", timeout=5)

def create_delta_lua():
    """🔥 ВСЕГДА перезаписывает Delta Lua файл при каждом запуске"""
    log(f"📝 ПЕРЕЗАПИСЫВАЮ Delta Lua: {DELTA_AUTOEXEC_PATH}")
    log(f"   📄 Содержимое: {DELTA_LUA_CONTENT}")
    
    try:
        folder = os.path.dirname(DELTA_AUTOEXEC_PATH)
        if not os.path.exists(folder):
            run_su(f"mkdir -p '{folder}'", timeout=5)
            log(f"   📁 Создана папка: {folder}")
        
        with open(DELTA_AUTOEXEC_PATH, 'w') as f:
            f.write(DELTA_LUA_CONTENT)
        
        run_su(f"chmod 644 '{DELTA_AUTOEXEC_PATH}'", timeout=3)
        
        try:
            with open(DELTA_AUTOEXEC_PATH, 'r') as f:
                content = f.read().strip()
            if content == DELTA_LUA_CONTENT:
                log("✅ Delta Lua перезаписан УСПЕШНО")
            else:
                log(f"⚠️ Содержимое отличается! Записано: {content[:50]}")
        except Exception as e:
            log(f"⚠️ Не удалось проверить содержимое: {e}")
        
        return True
    except Exception as e:
        log(f"❌ Ошибка перезаписи Lua: {e}")
        
        log("🔄 Пробую через su...")
        try:
            escaped_content = DELTA_LUA_CONTENT.replace("'", "'\"'\"'")
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

def kill_all_roblox():
    log("🛑 Убиваю ВСЕ процессы Roblox...")
    killed = 0
    ok, out, _ = run_su("pm list packages com.roblox", timeout=10)
    if ok:
        pkgs = [line.split(":")[1] for line in out.splitlines() if line.startswith("package:")]
        for pkg in pkgs:
            run_su(f"am force-stop {pkg}", timeout=5)
            killed += 1
    run_su("am force-stop com.android.chrome", timeout=5)
    run_su("am force-stop com.android.browser", timeout=5)
    log(f"   ✅ Остановлено: {killed} пакетов")
    time.sleep(2)

def launch_delta():
    log(f"🔓 Запускаю Дельту (com.roblox.client) СРАЗУ в плейс {PLACE_ID} для байпаса...")
    deep_link = f"'roblox://experiences/start?placeId={PLACE_ID}'"
    run_su(f"am start -a android.intent.action.VIEW -d {deep_link} {PACKAGE_MAIN}", timeout=10)

def get_farm_packages():
    """Возвращает список пакетов-клонов для фарма (кроме основного), максимум 4"""
    ok, out, _ = run_su("pm list packages com.roblox", timeout=10)
    if not ok:
        return []
    pkgs = [line.split(":")[1] for line in out.splitlines() if line.startswith("package:")]
    farm_pkgs = [pkg for pkg in pkgs if pkg != PACKAGE_MAIN]
    return farm_pkgs[:4]

def launch_roblox_light_farm():
    log("🚜 Запускаю ферму (Ожидание 15 сек -> Прямой запуск в плейс)...")
    farm_pkgs = get_farm_packages()
    if not farm_pkgs:
        log("⚠️ Нет пакетов для фарма")
        return []
    
    launched = 0
    for pkg in farm_pkgs:
        log(f"⏳ Ожидание {FARM_PRELAUNCH_DELAY} секунд перед запуском {pkg}...")
        time.sleep(FARM_PRELAUNCH_DELAY)
        
        deep_link = f"'roblox://experiences/start?placeId={PLACE_ID}'"
        log(f"🚀 Прямой запуск в плейс {PLACE_ID} для {pkg}...")
        run_su(f"am start -a android.intent.action.VIEW -d {deep_link} {pkg}", timeout=5)
        
        launched += 1
        time.sleep(2)
    
    log(f"   ✅ Фермеров запущено: {launched}")
    return farm_pkgs

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

def restart_pkg(pkg):
    """🔄 Принудительно останавливает пакет, ждет 15 сек и запускает его снова в плейс"""
    log(f"⚠️ Окно {pkg} не видно → останавливаю пакет...")
    run_su(f"am force-stop {pkg}", timeout=5)
    
    log(f"⏳ Ожидание {FARM_RESTART_DELAY} секунд перед перезапуском {pkg}...")
    time.sleep(FARM_RESTART_DELAY)
    
    deep_link = f"'roblox://experiences/start?placeId={PLACE_ID}'"
    log(f"🚀 Повторный запуск {pkg} в плейс {PLACE_ID}...")
    run_su(f"am start -a android.intent.action.VIEW -d {deep_link} {pkg}", timeout=5)

def monitor_farm(duration, farm_pkgs):
    """👁 Мониторинг фермы: каждые FARM_CHECK_INTERVAL секунд проверяет видимость окон"""
    if not farm_pkgs:
        log("⚠️ Нет пакетов для мониторинга, просто ждём...")
        time.sleep(duration)
        return
    
    log(f"👁 Мониторинг {len(farm_pkgs)} пакетов каждые {FARM_CHECK_INTERVAL} сек...")
    log(f"⏱️ Задержка перед перезапуском вылетевшего: {FARM_RESTART_DELAY} сек")
    
    end_time = time.time() + duration
    
    while time.time() < end_time:
        sleep_time = min(FARM_CHECK_INTERVAL, max(0, end_time - time.time()))
        if sleep_time > 0:
            time.sleep(sleep_time)
        
        if time.time() >= end_time:
            break
        
        log("🔍 Проверка видимости окон фермы...")
        win_out, act_out = get_visibility_snapshots()
        
        if win_out is None and act_out is None:
            log("⚠️ Не удалось получить dumpsys, пропускаю проверку")
            continue
        
        for pkg in farm_pkgs:
            if not is_pkg_visible(pkg, win_out, act_out):
                log(f"⚠️ {pkg} НЕ виден → перезапуск через {FARM_RESTART_DELAY} сек")
                restart_pkg(pkg)
                time.sleep(2)
            else:
                log(f"✅ {pkg} виден")
        
        remaining = end_time - time.time()
        if remaining > 0:
            log(f"⏳ До конца фарма: {remaining/60:.1f} мин")

def get_link_from_browser():
    try:
        res = subprocess.run(
            ["/data/data/com.termux/files/usr/bin/termux-clipboard-get"],
            capture_output=True, text=True, timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            match = re.search(r'(https?://[^\s\"\'<>\}\]\)\;]+)', res.stdout.strip())
            if match:
                return match.group(0).rstrip('.,;')
    except:
        pass
    
    ok, out, _ = run_su("/system/bin/dumpsys activity activities", timeout=5)
    if ok and out:
        match = re.search(r'(https?://[^\s\"\'<>\}\]\)\;]+)', out)
        if match:
            return match.group(0).rstrip('.,;')
    return None

def bypass_with_zen(url):
    if not ZEN_API_KEY or ZEN_API_KEY == "YOUR_API_KEY_HERE":
        log("❌ ZEN_API_KEY не настроен!")
        return None
    
    try:
        clean = url.strip()
        if not clean.startswith(("http://", "https://")):
            log("❌ Invalid URL")
            return None
        encoded = urllib.parse.quote(clean, safe=":/?=&#")
    except Exception as e:
        log(f"❌ URL encode error: {e}")
        return None
    
    endpoint = f"{ZEN_API_URL}?url={encoded}"
    headers = {"x-api-key": ZEN_API_KEY, "User-Agent": "FarmBot/16.2"}
    
    log(f"🔗 Запрос к ZEN-API: {clean[:60]}...")
    
    try:
        resp = requests.get(endpoint, headers=headers, timeout=30)
        log(f"📡 HTTP {resp.status_code}")
        
        if resp.status_code == 200:
            try:
                data = resp.json()
            except json.JSONDecodeError:
                log(f"❌ Invalid JSON: {resp.text[:100]}")
                return None
            
            if data.get("status") == "success" and isinstance(data.get("result"), str):
                key = data["result"].strip()
                if key.startswith("FREE_") or len(key) > 10:
                    log(f"✅ KEY: {key}")
                    return key
                else:
                    log(f"⚠️ Unexpected key format: {key[:20]}")
            else:
                log(f"⚠️ No key in response: {data}")
        elif resp.status_code == 401:
            log("❌ Invalid API key (401)")
        elif resp.status_code == 403:
            log(f"❌ Forbidden (403): {resp.text[:100]}")
        elif resp.status_code == 429:
            log("⏳ Rate limit (429) — жду 60 сек")
            time.sleep(60)
            return bypass_with_zen(url)
        else:
            log(f"❌ HTTP {resp.status_code}: {resp.text[:100]}")
    except requests.Timeout:
        log("⏰ Request timeout")
    except requests.ConnectionError:
        log("🌐 Connection error")
    except Exception as e:
        log(f"💥 Exception: {type(e).__name__}: {e}")
    
    return None

def inject_key(key):
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
                log(f"⚠️ Содержимое файла отличается: {content[:20]}...")
        except Exception as e:
            log(f"⚠️ Не удалось проверить файл (возможно, нужен su для чтения): {e}")
        
        return True
    
    except Exception as e:
        log(f"❌ Ошибка записи файла: {e}")
        return False

def load_state():
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                loaded = json.load(f)
                state.update(loaded)
        except:
            state = {"last_key_time": 0.0}

def save_state():
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except:
        pass

def run_bypass_cycle():
    for attempt in range(1, MAX_RETRIES + 1):
        log(f"🔁 Байпас {attempt}/{MAX_RETRIES}")
        
        kill_all_roblox()
        launch_delta()
        time.sleep(25)
        
        log("📺 Тап рекламы...")
        tap(AD_BTN_X, AD_BTN_Y)
        time.sleep(1.5)
        tap(AD_BTN_X, AD_BTN_Y)
        time.sleep(3)
        
        link = get_link_from_browser()
        if not link or not link.startswith("https://"):
            log("⚠️ Ссылка не найдена")
            time.sleep(2)
            continue
        
        key = bypass_with_zen(link)
        if not key:
            log("❌ Ключ не получен от ZEN-API")
            time.sleep(2)
            continue
        
        kill_all_roblox()
        time.sleep(2)
        
        if inject_key(key):
            state["last_key_time"] = time.time()
            save_state()
            log("💾 Таймер байпаса обновлён")
            return True
    
    return False

def main():
    global state
    log("🤖 Roblox Farm v16.2 FILE LICENSE INJECT START")
    log(f"🔗 ZEN-API: {'✅' if ZEN_API_KEY and ZEN_API_KEY != 'YOUR_API_KEY_HERE' else '❌ Не настроен'}")
    log(f"📁 Delta Lua: {DELTA_AUTOEXEC_PATH}")
    log(f"📁 Delta License: {DELTA_LICENSE_PATH}")
    log(f"⏱️ Фарм: {FARM_CYCLE_SECONDS//60} мин | Байпас: {'каждый цикл' if FORCE_BYPASS else '1 раз в 24ч'}")
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
    
    while True:
        now = time.time()
        elapsed = now - state["last_key_time"]
        
        if not FORCE_BYPASS and state["last_key_time"] > 0 and elapsed < BYPASS_COOLDOWN:
            log(f"⏱️ Кулдаун: {elapsed/3600:.1f}ч / 24ч → ПРОПУСК байпаса")
        else:
            log("🔓 Кулдаун истёк → запускаю байпас (СРАЗУ в плейс через com.roblox.client)")
            if not run_bypass_cycle():
                log("💥 Байпас провален, но продолжаю фарм")
        
        kill_all_roblox()
        farm_pkgs = launch_roblox_light_farm()
        log(f"💤 Фарм {FARM_CYCLE_SECONDS//60} мин с мониторингом каждые {FARM_CHECK_INTERVAL} сек...")
        monitor_farm(FARM_CYCLE_SECONDS, farm_pkgs)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("🛑 Остановлено пользователем")
    except Exception as e:
        log(f"💥 Crash: {e}")
        import traceback
        traceback.print_exc()
        time.sleep(60)
