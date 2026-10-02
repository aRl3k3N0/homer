"""
WebSocket-хаб для Web UI.

Каждое подключение — подписчик. Есть метод broadcast(event) —
рассылает всем.

События:
    {'type': 'job.updated', 'job': {...}}
    {'type': 'job.created', 'job': {...}}
    {'type': 'job.removed', 'job_id': 42}
    {'type': 'stats.updated', 'stats': {...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Set

from fastapi import WebSocket

_log = logging.getLogger('homer.webui.ws')


class WSHub:
    def __init__(self):
        self._subscribers: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._subscribers.add(ws)
        _log.debug(f"WS подключён, всего: {len(self._subscribers)}")

    async def unsubscribe(self, ws: WebSocket):
        async with self._lock:
            self._subscribers.discard(ws)
        _log.debug(f"WS отключён, всего: {len(self._subscribers)}")

    async def broadcast(self, event: dict[str, Any]):
        payload = json.dumps(event, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._subscribers):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.unsubscribe(ws)

    @property
    def count(self) -> int:
        return len(self._subscribers)


# Глобальный хаб — один на приложение
_hub: WSHub | None = None


def get_hub() -> WSHub:
    global _hub
    if _hub is None:
        _hub = WSHub()
    return _hub
