"""
WebSocket-подключение к серверу.
Подключение, реконнект с бэкоффом, JSON туда-обратно.
"""
import json
import websockets


class Connection:
    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.connected = False
        self._backoff = 5

    async def connect(self):
        self.ws = await websockets.connect(
            self.url,
            ping_interval=20,   # WS-пинг: детект мёртвой связи
            ping_timeout=10,
            close_timeout=5,
        )
        self.connected = True
        self._backoff = 5      # удачный коннект → сброс бэкоффа
        return self.ws

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
        self.connected = False

    def next_delay(self) -> int:
        """5 → 10 → 20 → 40 → 60 (макс)"""
        delay = self._backoff
        self._backoff = min(self._backoff * 2, 60)
        return delay

    async def send(self, data: dict):
        if not self.ws:
            raise ConnectionError("not connected")
        await self.ws.send(json.dumps(data))

    async def recv(self) -> dict:
        raw = await self.ws.recv()
        return json.loads(raw)
