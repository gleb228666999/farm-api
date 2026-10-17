#!/usr/bin/env python3
"""
APKManager — установка/обновление APK одной кнопкой (⬇ APK в дашборде).

Источники ссылок (link-apps):
    https://raw.githubusercontent.com/staffere228-alt/apk/refs/heads/main/link-apps

Формат link-apps: одна ссылка на строку. Поддерживаются:
    - пустые строки и #комментарии;
    - «имя|ссылка» (имя — произвольная метка, последний элемент = URL).

Как работает run_apk_update():
    1. качает список ссылок;
    2. снимает versionCode всех сторонних пакетов (pm list packages -3 --show-versioncode,
       фоллбэк — dumpsys package);
    3. для каждого APK: скачал (проверка PK-магии = валидный zip/APK) →
       pm install -r -d через su (обновление поверх + разрешение даунгрейда);
    4. переснимает versionCode: появился новый пакет или сменился versionCode
       → это РЕАЛЬНОЕ обновление;
    5. если было хотя бы одно обновление → reboot_now=True
       (перезагрузку телефона выполняет client/main.py ПОСЛЕ отправки
       результата на сервер — чтобы дашборд успел всё показать).

Зависимостей нет — только stdlib. Логи → stdout → logs/services/../client.log.
"""
import os
import re
import shutil
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

APK_LINKS_URL = "https://raw.githubusercontent.com/staffere228-alt/apk/refs/heads/main/link-apps"
APK_DIR_NAME = "info/apk"          # ~/farm/info/apk — временные APK, чистятся сами
UA = "FarmClient-APK/1.0"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- su (PATH может быть побит root-стражем) ----------

def find_su() -> str:
    for cand in ("su", "/system/bin/su", "/system/xbin/su", "/sbin/su"):
        found = shutil.which(cand)
        if found:
            return found
        if cand.startswith("/") and os.path.exists(cand):
            return cand
    return "su"


SU_BIN = find_su()


def su_run(cmd, timeout=60):
    try:
        res = subprocess.run([SU_BIN, "-c", cmd], capture_output=True,
                             text=True, timeout=timeout)
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return False, "", str(e)


# ---------- список ссылок ----------

def parse_links(text: str) -> list:
    """['url', 'имя|url', '#комментарий', ...] -> [{'name','url'}, ...]"""
    links = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 2:
            links.append({"name": parts[0], "url": parts[-1]})
        else:
            fname = urllib.parse.urlparse(line).path.rsplit("/", 1)[-1] \
                or f"app{len(links) + 1}"
            links.append({"name": fname, "url": line})
    return links


def http_get(url: str, timeout=90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_apk(url: str, dest: Path):
    """Скачивает APK в dest (через .part). Проверяет PK-магию (валидный zip/APK).
    Возвращает (ok, сообщение)."""
    tmp = dest.with_suffix(".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        total = 0
        with urllib.request.urlopen(req, timeout=90) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                total += len(chunk)
                f.write(chunk)
        if total == 0:
            tmp.unlink(missing_ok=True)
            return False, "пустой ответ"
        with open(tmp, "rb") as f:
            magic = f.read(4)
        if magic[:2] != b"PK":
            tmp.unlink(missing_ok=True)
            return False, f"это не APK/zip (magic={magic!r}), размер {total}"
        tmp.replace(dest)
        mb = total / (1024 * 1024)
        return True, (f"{mb:.1f} МБ" if mb >= 1 else f"{total // 1024} КБ")
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"{type(e).__name__}: {e}"


# ---------- установленные пакеты ----------

def installed_versions() -> dict:
    """{package: versionCode} всех сторонних пакетов (или всех, через dumpsys)."""
    vers = {}
    ok, out, _ = su_run("pm list packages -3 --show-versioncode", timeout=90)
    if ok and out:
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("package:"):
                continue
            parts = line[len("package:"):].split()
            if not parts:
                continue
            v = None
            for tok in parts[1:]:
                if "versionCode" in tok:
                    m = re.search(r"(\d+)", tok)
                    if m:
                        v = int(m.group(1))
            vers[parts[0]] = v
    if not vers:  # фоллбэк: dumpsys (все пакеты, включая системные)
        ok, out, _ = su_run("dumpsys package", timeout=120)
        if ok:
            cur = None
            for line in out.splitlines():
                m = re.search(r"Package \[(\S+)\]", line)
                if m:
                    cur = m.group(1)
                    continue
                if cur and "versionCode=" in line and cur not in vers:
                    m = re.search(r"versionCode=(\d+)", line)
                    if m:
                        vers[cur] = int(m.group(1))
    return vers


def diff_versions(before: dict, after: dict) -> list:
    """Что появилось нового или сменило versionCode."""
    changed = []
    for pkg, v in after.items():
        if pkg not in before:
            changed.append({"pkg": pkg, "from": None, "to": v})
        elif before[pkg] != v:
            changed.append({"pkg": pkg, "from": before[pkg], "to": v})
    return changed


# ---------- установка ----------

def pm_install(apk: Path):
    """pm install -r -d (reinstall поверх + разрешить даунгрейд). 10 мин на большой APK."""
    ok, sout, serr = su_run(f"pm install -r -d '{apk}'", timeout=600)
    text = f"{sout} {serr}".strip()
    return (ok and "Success" in text), (text or "нет вывода pm")


def run_apk_update(payload: dict) -> dict:
    """Синхронная (вызывается из client/main.py через asyncio.to_thread)."""
    links_url = payload.get("links_url") or APK_LINKS_URL
    out = {"ok": True, "links_url": links_url, "installed": [],
           "updated_any": False, "reboot_now": False}

    try:
        text = http_get(links_url).decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"не смог скачать список ссылок: {e}"}

    links = parse_links(text)
    if not links:
        return {"ok": False, "error": "список ссылок пуст"}

    log(f"📲 APK: {len(links)} ссылок ({links_url})")

    base = Path(__file__).resolve().parents[1]     # core/apk_manager.py -> ~/farm
    apk_dir = base / APK_DIR_NAME
    apk_dir.mkdir(parents=True, exist_ok=True)

    before = installed_versions()
    if not before:
        log("⚠️ не удалось снять список пакетов — diff обновлений будет неточным")

    for i, item in enumerate(links, 1):
        name, url = item["name"], item["url"]
        rec = {"name": name, "url": url}
        out["installed"].append(rec)
        log(f"📲 [{i}/{len(links)}] {name}")

        if not url.lower().startswith(("http://", "https://")):
            rec.update(ok=False, error="не ссылка")
            out["ok"] = False
            continue

        dest = apk_dir / f"app_{i}.apk"
        ok, msg = download_apk(url, dest)
        if not ok:
            rec.update(ok=False, error=msg[-200:])
            out["ok"] = False
            log(f"   ❌ скачивание: {msg[-120:]}")
            continue

        log(f"   📥 скачан ({msg}), ставлю через pm install -r -d ...")
        ok, pmsg = pm_install(dest)
        rec["pm"] = pmsg[-200:]

        after = installed_versions()
        changed = diff_versions(before, after)
        before = after

        if ok and changed:
            rec.update(ok=True, changed=changed)
            out["updated_any"] = True
            log(f"   ✅ обновлено: {', '.join(c['pkg'] for c in changed)}")
        elif ok:
            rec.update(ok=True, changed=[], note="версия не изменилась")
            log("   ⚪ поставлен, версия не изменилась")
        else:
            rec.update(ok=False, error=pmsg[-200:])
            out["ok"] = False
            log(f"   ❌ pm: {pmsg[-120:]}")

        try:
            dest.unlink()
        except Exception:
            pass

    # reboot: {"reboot":true} — всегда, {"reboot":false} — никогда,
    # без ключа — только если реально что-то обновилось
    if "reboot" in payload:
        out["reboot_now"] = bool(payload.get("reboot"))
    else:
        out["reboot_now"] = out["updated_any"]

    log(f"🏁 APK готов: ok={out['ok']}, обновлений={out['updated_any']}, "
        f"reboot={out['reboot_now']}")
    return out


def reboot_phone() -> bool:
    """Полная перезагрузка телефона (su). Вызывается ПОСЛЕ отправки результата."""
    log("📱 su -c reboot ...")
    ok, _, _ = su_run("reboot", timeout=20)
    if not ok:
        ok, _, _ = su_run("setprop sys.powerctl reboot", timeout=20)
    if not ok:
        log("❌ перезагрузка не сработала")
    return ok
