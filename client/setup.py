#!/usr/bin/env python3
"""
🔧 Неубиваемость v5 — ВСЕ механизмы автозапуска по приоритету:
  1. init.rc в /system        (если remount возможен)
  2. /data/adb/service.d      (если есть Magisk/KernelSU/APatch)
  3. Termux:Boot              (скачивает и ставит APK сам!)
  4. ~/.bashrc                (открыл Termux → ожило)
Страж и лог: /data/local/tmp/farm-keeper.log
Запуск: python setup.py [--no-start]
"""
import os
import sys
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
FARM = HOME / "farm"
BASHERC = HOME / ".bashrc"
PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
BOOT_DIR = HOME / ".termux" / "boot"

TERMUX_BOOT_APK = ("https://github.com/termux/termux-boot/releases/download/"
                   "v0.8.1/termux-boot_v0.8.1+github-debug_universal.apk")

BASHRC_MARK = "# === FARM-AUTO v2 ==="
BASHRC_HOOK = BASHRC_MARK + """
if [ -f "$HOME/farm/supervisor.sh" ]; then
  nohup sh "$HOME/farm/supervisor.sh" >/dev/null 2>&1 &
fi
"""

BOOT_SCRIPT = """#!/data/data/com.termux/files/usr/bin/sh
# Запускается Termux:Boot'ом после загрузки телефона
termux-wake-lock
sh "$HOME/farm/supervisor.sh"
"""

LAUNCHER_MGR = (
    "#!/system/bin/sh\n"
    "exec /system/bin/sh /data/data/com.termux/files/home/farm/keeper.sh\n"
)

SYSTEM_LAUNCHER = """#!/system/bin/sh
K=/data/data/com.termux/files/home/farm/keeper.sh
while :; do
    [ -r "$K" ] && break
    /system/bin/sleep 5
done
exec /system/bin/sh "$K"
"""

RC_TEMPLATE = """service farmkeeper /system/bin/sh /system/etc/farmkeeper.sh
    class late_start
    user root
    group root
    disabled
    oneshot{seclabel}

on property:sys.boot_completed=1
    start farmkeeper
"""


def sh(cmd, root=False, timeout=30):
    if root:
        cmd = f'su -c "{cmd}"'
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def su_write_file(content: str, dest: str, mode: str) -> bool:
    tmp = FARM / ".tmp_root_write"
    tmp.write_text(content)
    ok, _, _ = sh(f"cp '{tmp}' '{dest}' && chmod {mode} '{dest}' "
                  f"&& chown 0:0 '{dest}' && echo ok", root=True)
    tmp.unlink(missing_ok=True)
    return ok


def try_init_rc() -> bool:
    """Слой 6a: /system/etc/init/farmkeeper.rc (только если /system RW)"""
    ok, _, _ = sh("mount -o remount,rw /system", root=True)
    if not ok:
        ok, _, _ = sh("mount -o remount,rw /", root=True)
    # реальная проверка, а не код возврата
    writable, _, _ = sh("touch /system/.farmtest && rm /system/.farmtest && echo ok",
                        root=True)
    if not writable:
        print("   ⛔ /system read-only (verity) — init.rc недоступен")
        return False

    _, enforce, _ = sh("getenforce", root=True)
    seclabel = "\n    seclabel u:r:su:s0" if "enforc" in (enforce or "").lower() else ""
    sh("mkdir -p /system/etc/init", root=True)
    ok1 = su_write_file(SYSTEM_LAUNCHER, "/system/etc/farmkeeper.sh", "755")
    ok2 = su_write_file(RC_TEMPLATE.format(seclabel=seclabel),
                        "/system/etc/init/farmkeeper.rc", "644")
    sh("mount -o remount,ro /system 2>/dev/null; "
       "mount -o remount,ro / 2>/dev/null; true", root=True)
    if ok1 and ok2:
        print("   ✅ init.rc установлен (автозапуск на уровне системы)")
        return True
    print("   ❌ не смог записать в /system")
    return False


def try_service_d() -> bool:
    """Слой 6b: service.d (Magisk/KernelSU/APatch)"""
    _, adbls, _ = sh("ls /data/adb/", root=True)
    adbls = (adbls or "").lower()
    if not any(k in adbls for k in ("magisk", "ksu", "ap")):
        return False
    tmp = FARM / ".98farm_launcher"
    tmp.write_text(LAUNCHER_MGR)
    ok_any = False
    for t in ("/data/adb/service.d",
              "/data/adb/ksu/post-fs-data.d",
              "/data/adb/ap/service.d"):
        if ("magisk" in adbls and "service.d" in t) or \
           ("ksu" in adbls and "ksu" in t) or \
           ("ap" in adbls and "/ap/" in t):
            ok, _, _ = sh(f"mkdir -p {t} && cp '{tmp}' {t}/98farm.sh && "
                          f"chmod 755 {t}/98farm.sh && echo ok", root=True)
            if ok:
                print(f"   ✅ service.d → {t}/98farm.sh")
                ok_any = True
    tmp.unlink(missing_ok=True)
    return ok_any


def try_termux_boot() -> bool:
    """Слой 5: Termux:Boot — при необходимости ставим APK сами (через root)."""
    # boot-скрипт ставим ВСЕГДА — он безвреден без APK
    BOOT_DIR.mkdir(parents=True, exist_ok=True)
    boot_sh = BOOT_DIR / "farm.sh"
    boot_sh.write_text(BOOT_SCRIPT)
    os.chmod(boot_sh, 0o755)
    print("   ✅ ~/.termux/boot/farm.sh")

    installed, _, _ = sh("pm list packages com.termux.boot", root=True)
    if installed:
        print("   ✅ Termux:Boot уже установлен — автозапуск будет работать")
        return True

    # ставим APK сами
    print("   📥 Termux:Boot нет — скачиваю APK...")
    try:
        req = urllib.request.Request(TERMUX_BOOT_APK,
                                     headers={"User-Agent": "FarmSetup/5"})
        apk = FARM / ".termux-boot.apk"
        apk.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        ok, out, err = sh(f"pm install '{apk}'", root=True, timeout=120)
        apk.unlink(missing_ok=True)
        if ok:
            print("   ✅ Termux:Boot УСТАНОВЛЕН автоматически")
            print("   ⚠️ ОДИН РАЗ открой приложение Termux:Boot на телефоне!")
            print("      (иначе Android не отдаст ему BOOT_COMPLETED)")
            return True
        print(f"   ❌ pm install не удался: {err or out}")
    except Exception as e:
        print(f"   ❌ скачать APK не удалось: {e}")
    print("   👉 Поставь руками из F-Droid: приложение «Termux:Boot», открыть 1 раз")
    return False


def main():
    no_start = "--no-start" in sys.argv
    print("\n" + "=" * 46)
    print("🔧 НЕУБИВАЕМОСТЬ v5")
    print("=" * 46)

    have_root, _, _ = sh("id | grep -q uid=0", root=True)
    print(f"   root: {'✅' if have_root else '❌'}")

    # --- 0. чистка старого ---
    sh("pkill -f 'keeper[.]sh'", root=True, timeout=10)
    sh("pkill -f 'supervisor[.]sh'", timeout=10)
    sh("rm -f /data/local/tmp/.farm_supervisor.lock /data/local/tmp/.farm_keeper.pid", root=True)
    (FARM / "info" / "STOP").unlink(missing_ok=True)
    sh("rm -f /data/local/tmp/.farm_stop", root=True)
    svc = Path(PREFIX) / "var" / "service" / "farmd"
    if svc.exists():
        subprocess.run([f"{PREFIX}/bin/sv", "down", "farmd"],
                       capture_output=True, timeout=10)
        shutil.rmtree(svc, ignore_errors=True)
    print("   ✅ чистка ок")

    # --- 1. права ---
    for f in ("supervisor.sh", "keeper.sh", "farm_stop.sh", "farm_start.sh"):
        p = FARM / f
        if p.exists():
            os.chmod(p, 0o755)
    print("   ✅ скрипты готовы")

    # --- 2. bashrc (слой 4) ---
    rc = BASHERC.read_text() if BASHERC.exists() else ""
    for mark in (BASHRC_MARK, "# === FARM-AUTO ==="):
        if mark in rc:
            rc = rc.split(mark)[0].rstrip() + "\n"
    BASHERC.write_text(rc + "\n" + BASHRC_HOOK)
    print("   ✅ хук ~/.bashrc")

    # --- 3. автозапуск: все механизмы по очереди ---
    print("\n   ── механизмы автозапуска ──")
    got_boot = False
    if have_root:
        got_boot |= try_init_rc()      # /system (если открыт)
        got_boot |= try_service_d()    # root-менеджер (если есть)
    got_boot |= try_termux_boot()      # BOOT_COMPLETED — ставим всегда
    if not got_boot:
        print("\n   ⚠️ НИ ОДИН механизм автозапуска не установлен!")
        print("      После ребута: открыть Termux руками (bashrc поднимет всё)")

    # --- 4. страж: запускаем, если есть откуда ---
    if have_root:
        # init.rc/service.d запустят стража при загрузке; сейчас запустим руками,
        # чтобы охрана работала до первого ребута
        alive, _, _ = sh("ps -A -o ARGS | grep 'keeper.sh' | grep -v grep", root=True)
        if not alive:
            sh("setsid /system/bin/sh "
               "/data/data/com.termux/files/home/farm/keeper.sh "
               ">/dev/null 2>&1 &", root=True)
            time.sleep(4)
            alive, _, _ = sh("ps -A -o ARGS | grep 'keeper.sh' | grep -v grep",
                             root=True)
        print(f"\n   {'✅' if alive else '⚠️'} root-страж (до ребута): "
              f"{'жив, лог: /data/local/tmp/farm-keeper.log' if alive else 'не запустился'}")
        sh("dumpsys deviceidle whitelist +com.termux", root=True)

    # --- 5. маркер v5 ---
    (FARM / "info").mkdir(exist_ok=True)
    (FARM / "info" / "setup_done.json").write_text(json.dumps({"v": 5}))

    # --- 6. supervisor ---
    if not no_start:
        ok, _, _ = sh("pgrep -f 'supervisor[.]sh'")
        if not ok:
            subprocess.Popen(["sh", str(FARM / "supervisor.sh")],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
            print("   ✅ supervisor запущен")
        else:
            print("   ℹ️  supervisor уже работает")

    print("\n🎉 Готово!")
    print("   Стоп: sh ~/farm/farm_stop.sh | Запуск: sh ~/farm/farm_start.sh")


if __name__ == "__main__":
    main()
