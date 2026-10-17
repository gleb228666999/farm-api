"""
EventOutbox — надёжная доставка событий фарма и регы на сервер (ЭТАП 2 + v0.10).

Путь события:  фарм → info/farm_events.jsonl   ┐
               рега → info/rega_events.jsonl   ┘→ (этот модуль) → WS → сервер → SQLite.

Принцип outbox:
- фарм/рега ТОЛЬКО пишут в свои jsonl (один файл — один писатель);
- этот модуль ТОЛЬКО читает их и ведёт offsets в info/events_offset.json;
- offset двигается ТОЛЬКО после подтверждения сервера (events_ack) —
  если связь умерла, недоставленное уйдёт при следующем коннекте;
- если ack потерялся и батч ушёл повторно — дубликаты отсечёт сервер
  (у каждого события есть id, PRIMARY KEY в SQLite).

Батчи берутся последовательно: сначала все события фарма, потом регы
(протокол не менялся: один батч — один events_ack).

Только stdlib. Никогда не бросает исключений наружу — клиент не должен
умереть из-за проблем с событиями.
"""
import json
from pathlib import Path


class _FileReader:
    """Читатель одного jsonl-файла с байтовым offset (как farm_events в v0.8)."""

    def __init__(self, path: Path, offset: int = 0):
        self.path = path
        self.offset = max(0, offset)
        self.batch_end = None

    def pending(self, limit: int) -> list:
        self.batch_end = None
        try:
            if not self.path.exists():
                return []
            size = self.path.stat().st_size
            if self.offset > size:
                self.offset = 0        # файл провернули (ротация) — дубли отсечёт сервер
            if self.offset >= size:
                return []
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read(size - self.offset)
            nl = data.rfind(b"\n")
            if nl == -1:
                return []
            chunk = data[:nl + 1]
            self.batch_end = self.offset + len(chunk)
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
            self.batch_end = None
            return []

    def commit(self, accepted: int):
        if accepted <= 0 or self.batch_end is None:
            return
        self.offset = self.batch_end
        self.batch_end = None


class EventOutbox:
    """События из farm_events.jsonl + rega_events.jsonl (v0.10)."""

    SOURCES = ("farm", "rega")     # порядок доставки: сначала фарм, потом рега

    def __init__(self, base: Path):
        self.offset_file = base / "info" / "events_offset.json"
        offs = self._load_offsets()
        self.readers = {
            "farm": _FileReader(base / "info" / "farm_events.jsonl", offs.get("farm", 0)),
            "rega": _FileReader(base / "info" / "rega_events.jsonl", offs.get("rega", 0)),
        }
        self._active = None         # источник, чей батч сейчас в полёте

    # ---------- offsets (переживают рестарт клиента) ----------

    def _load_offsets(self) -> dict:
        try:
            o = json.loads(self.offset_file.read_text())
            return o if isinstance(o, dict) else {"offset": o}
        except Exception:
            return {}

    def _save_offsets(self):
        try:
            data = {k: r.offset for k, r in self.readers.items()}
            tmp = self.offset_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(self.offset_file)     # атомарно
        except Exception:
            pass

    # ---------- чтение ----------

    def pending(self, limit: int = 50) -> list:
        """Очередь неотправленных событий (максимум limit, только ЦЕЛЫЕ строки).
        Сначала доправляем фарм, потом регу."""
        for name in self.SOURCES:
            evs = self.readers[name].pending(limit)
            if evs:
                self._active = name
                return evs
        self._active = None
        return []

    def commit(self, accepted: int):
        """Сервер подтвердил приём батча → двигаем offset того файла, из которого батч."""
        if self._active is None:
            return
        self.readers[self._active].commit(accepted)
        self._active = None
        self._save_offsets()

    def unsent(self) -> int:
        """Сколько байт событий ждёт отправки (для диагностики)."""
        n = 0
        for r in self.readers.values():
            try:
                if r.path.exists():
                    n += max(0, r.path.stat().st_size - r.offset)
            except Exception:
                pass
        return n
