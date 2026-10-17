"""
EventOutbox — надёжная доставка событий фарма на сервер (ЭТАП 2).

Путь события:  фарм → info/farm_events.jsonl → (этот модуль) → WS → сервер → SQLite.

Принцип outbox:
- фарм ТОЛЬКО пишет в farm_events.jsonl (один файл — один писатель);
- этот модуль ТОЛЬКО читает его и ведёт offset в info/events_offset.json;
- offset двигается ТОЛЬКО после подтверждения сервера (events_ack) —
  если связь умерла, недоставленное уйдёт при следующем коннекте;
- если ack потерялся и батч ушёл повторно — дубликаты отсечёт сервер
  (у каждого события есть id, PRIMARY KEY в SQLite).

Только stdlib. Никогда не бросает исключений наружу — клиент не должен
умереть из-за проблем с событиями.
"""
import json
from pathlib import Path


class EventOutbox:
    def __init__(self, base: Path):
        self.events_file = base / "info" / "farm_events.jsonl"
        self.offset_file = base / "info" / "events_offset.json"
        self.offset = self._load_offset()
        self._batch_end = None      # конец полного батча (байт-offset после последней \n)

    # ---------- offset (переживает рестарт клиента) ----------

    def _load_offset(self) -> int:
        try:
            return int(json.loads(self.offset_file.read_text()).get("offset", 0))
        except Exception:
            return 0

    def _save_offset(self):
        try:
            tmp = self.offset_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"offset": self.offset}))
            tmp.replace(self.offset_file)   # атомарно
        except Exception:
            pass

    # ---------- чтение ----------

    def pending(self, limit: int = 50) -> list:
        """Очередь неотправленных событий (максимум limit, только ЦЕЛЫЕ строки)."""
        try:
            self._batch_end = None
            if not self.events_file.exists():
                return []
            size = self.events_file.stat().st_size
            if self.offset > size:
                # файл провернули (ротация фарма) → читаем с начала;
                # дубликаты отсечёт сервер по id
                self.offset = 0
            if self.offset >= size:
                return []

            with open(self.events_file, "rb") as f:
                f.seek(self.offset)
                data = f.read(size - self.offset)

            # берём только строки, закончившиеся \n (последняя может быть дописана)
            nl = data.rfind(b"\n")
            if nl == -1:
                return []
            chunk = data[:nl + 1]
            self._batch_end = self.offset + len(chunk)

            events = []
            for line in chunk.decode(errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if isinstance(ev, dict) and ev.get("id"):
                        events.append(ev)
                except Exception:
                    pass
            return events[:limit]
        except Exception:
            self._batch_end = None
            return []

    def commit(self, accepted: int):
        """Сервер подтвердил приём батча → двигаем offset."""
        if accepted <= 0 or self._batch_end is None:
            return
        self.offset = self._batch_end
        self._batch_end = None
        self._save_offset()

    def unsent(self) -> int:
        """Сколько байт событий ждёт отправки (для диагностики)."""
        try:
            if not self.events_file.exists():
                return 0
            return max(0, self.events_file.stat().st_size - self.offset)
        except Exception:
            return 0
