"""
ProcessManager — управление сервисами (subprocess) на телефоне.
- манифест:  services/services.json
- логи:      logs/services/<name>.log
- desired:   info/services_state.json (переживает всё)
- pid-файлы: info/pids/<name>.pid     (усыновление после рестарта main)
- failing:   5 падений за 3 мин → перезапуски прекращаются
"""
import os
import json
import time
import signal
import subprocess
import threading
from pathlib import Path

# root-страж может поднять клиента с побитым PATH — фиксируем Termux
TERMUX_BIN = "/data/data/com.termux/files/usr/bin"
ENV = {**os.environ, "PATH": f"{TERMUX_BIN}:{os.environ.get('PATH', '')}"}


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # процесс чужой, но живой


class ProcessManager:
    def __init__(self, base: Path):
        self.base = base
        self.pid_dir = base / "info" / "pids"
        self.log_dir = base / "logs" / "services"
        self.state_file = base / "info" / "services_state.json"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.manifest = self._load_manifest()
        self.children = {}                      # name -> Popen (наши дети)
        self.desired = self._load_desired()     # name -> running|stopped
        self.failing = set()
        self._restarts = {}
        self._lock = threading.RLock()

    # ---------- манифест и desired ----------

    def _load_manifest(self) -> dict:
        try:
            return json.loads((self.base / "services" / "services.json").read_text())
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"[PM] ⚠️ битый services.json: {e}")
            return {}

    def _load_desired(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except Exception:
            # первый запуск: desired = autostart из манифеста
            return {n: ("running" if s.get("autostart") else "stopped")
                    for n, s in self.manifest.items()}

    def _save_desired(self):
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.desired))
        tmp.replace(self.state_file)            # атомарно

    # ---------- pid-файлы ----------

    def _pid_path(self, name): return self.pid_dir / f"{name}.pid"

    def _read_pid(self, name):
        try:
            return int(self._pid_path(name).read_text().strip())
        except Exception:
            return None

    def _write_pid(self, name, pid):
        self._pid_path(name).write_text(str(pid))

    def _clear_pid(self, name):
        self._pid_path(name).unlink(missing_ok=True)

    def _cmd_signature(self, name) -> str:
        """Отличительная часть команды (путь со слэшем)"""
        cmd = self.manifest.get(name, {}).get("command", "")
        parts = [t for t in cmd.split() if "/" in t]
        return parts[0] if parts else ""

    def _pid_belongs(self, pid, name) -> bool:
        """Жив ли И наш ли это процесс (pid могли переиспользовать после ребута)"""
        if not pid or not pid_alive(pid):
            return False
        sig = self._cmd_signature(name)
        if not sig:
            return True
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
            return sig in cmdline.replace("\x00", " ")
        except Exception:
            return False

    # ---------- состояние ----------

    def get_pid(self, name):
        proc = self.children.get(name)
        if proc and proc.poll() is None:
            return proc.pid
        return self._read_pid(name)

    def is_running(self, name) -> bool:
        proc = self.children.get(name)
        if proc is not None:
            return proc.poll() is None
        # не наш ребёнок (main перезапускался) — смотрим pid-файл
        return self._pid_belongs(self._read_pid(name), name)

    # ---------- управление ----------

    def start(self, name) -> dict:
        with self._lock:
            if name not in self.manifest:
                return {"ok": False, "error": f"unknown service '{name}'"}
            if self.is_running(name):
                return {"ok": False, "error": "already running",
                        "pid": self.get_pid(name)}

            svc = self.manifest[name]
            log_file = open(self.log_dir / f"{name}.log", "ab")
            try:
                proc = subprocess.Popen(
                    svc["command"],
                    shell=True,
                    cwd=str(self.base),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,   # своя группа процессов
                    env=ENV,                  # PATH с Termux — даже если нас поднял root
                )
            except Exception as e:
                return {"ok": False, "error": str(e)}

            self.children[name] = proc
            self._write_pid(name, proc.pid)
            self.desired[name] = "running"
            self._save_desired()
            self.failing.discard(name)        # ручной старт снимает failing
            self._restarts.pop(name, None)
            return {"ok": True, "pid": proc.pid}

    def stop(self, name, timeout=10) -> dict:
        with self._lock:
            if name not in self.manifest:
                return {"ok": False, "error": f"unknown service '{name}'"}

            pid = self.get_pid(name)
            if not pid or not self.is_running(name):
                self.children.pop(name, None)
                self._clear_pid(name)
                self.desired[name] = "stopped"
                self._save_desired()
                return {"ok": True, "status": "was not running"}

            # TERM всей группе (sh + python внутри)
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

            deadline = time.time() + timeout
            while time.time() < deadline and self.is_running(name):
                time.sleep(0.3)

            if self.is_running(name):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

            proc = self.children.pop(name, None)
            if proc:
                try: proc.wait(timeout=3)
                except Exception: pass
            self._clear_pid(name)
            self.desired[name] = "stopped"
            self._save_desired()
            return {"ok": True}

    def status(self) -> dict:
        with self._lock:
            out = {}
            for name, svc in self.manifest.items():
                running = self.is_running(name)
                out[name] = {
                    "running": running,
                    "pid": self.get_pid(name) if running else None,
                    "desired": self.desired.get(name, "stopped"),
                    "type": svc.get("type", "daemon"),
                    "restart": bool(svc.get("restart")),
                    "failing": name in self.failing,
                }
            return out

    # ---------- watchdog ----------

    def _note_restart(self, name) -> bool:
        """True = слишком часто (crash-loop)"""
        now = time.time()
        lst = [t for t in self._restarts.get(name, []) if now - t < 180]
        lst.append(now)
        self._restarts[name] = lst
        return len(lst) >= 5

    def reanimate(self) -> list:
        """Перезапустить умершие сервисы, которые ДОЛЖНЫ работать.
        🆕 v0.26: desired ПЕРЕЧИТЫВАЕТСЯ С ДИСКА каждый цикл. services_state.json —
        общий файл: сервис rega (rearm_farm) пишет туда farm=running НАПРЯМУЮ,
        минуя PM в памяти. Раньше desired грузился ОДИН раз при старте main,
        поэтому внешний реарм игнорировался: рега заканчивала («акки зарегало»),
        а фарм не поднимался никогда (жалоба хозяина 25.10: «фарм/байпас не
        происходит»). Теперь реарм видим watchdog'у ≤10с."""
        with self._lock:
            try:
                disk = json.loads(self.state_file.read_text())
                if isinstance(disk, dict):
                    self.desired.update(disk)       # внешний реарм → память
            except Exception:
                pass                                # битый/нет файла — память надёжнее
            restarted = []
            for name, svc in self.manifest.items():
                if not svc.get("restart"):
                    continue
                if self.desired.get(name) != "running":
                    continue
                if name in self.failing:
                    continue
                if self.is_running(name):
                    continue

                proc = self.children.pop(name, None)
                if proc:
                    try: proc.wait(timeout=1)
                    except Exception: pass
                self._clear_pid(name)

                if self._note_restart(name):
                    self.failing.add(name)
                    print(f"[PM] ⚠️ '{name}' падает слишком часто — failing")
                    continue

                r = self.start(name)
                if r.get("ok"):
                    restarted.append(name)
            return restarted

    def autostart(self) -> list:
        """Реальность → desired (при старте main)"""
        with self._lock:
            started = []
            for name in self.manifest:
                if self.desired.get(name) == "running" and not self.is_running(name):
                    r = self.start(name)
                    if r.get("ok"):
                        started.append(name)
            return started
