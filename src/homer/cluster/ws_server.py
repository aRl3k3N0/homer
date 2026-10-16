"""
WebSocket hub with per-subscriber backpressure.

Each subscriber gets its own bounded asyncio.Queue and a dedicated
writer task. If the queue overflows, the subscriber is disconnected
and removed -- no unbounded memory growth, no blocked broadcasters.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import WebSocket

_log = logging.getLogger("homer.cluster.ws")


_QUEUE_MAXSIZE = 100


class _Subscriber:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self.task: Optional[asyncio.Task] = None
        self.dropped: int = 0

    async def start(self):
        self.task = asyncio.create_task(self._writer(), name="ws-writer")

    async def _writer(self):
        try:
            while True:
                payload = await self.queue.get()
                if payload is None:
                    return
                await self.ws.send_text(payload)
        except Exception as e:
            _log.debug("ws writer stopped: %s", e)

    def try_put(self, payload: str) -> bool:
        try:
            self.queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False

    async def close(self):
        try:
            await self.queue.put(None)
        except Exception:
            pass
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except Exception:
                pass


class ChangeHub:
    def __init__(self):
        self._subs: dict[int, _Subscriber] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, ws: WebSocket):
        await ws.accept()
        sub = _Subscriber(ws)
        async with self._lock:
            self._subs[id(ws)] = sub
        await sub.start()
        _log.info("cluster ws: subscriber connected (%d total)",
                  len(self._subs))

    async def unsubscribe(self, ws: WebSocket):
        async with self._lock:
            sub = self._subs.pop(id(ws), None)
        if sub is not None:
            await sub.close()
        _log.info("cluster ws: subscriber disconnected (%d left)",
                  len(self._subs))

    async def broadcast(self, event: dict[str, Any]):
        payload = json.dumps(event, ensure_ascii=False, default=str)
        async with self._lock:
            subs = list(self._subs.items())
        # Non-blocking: push to each queue, drop slow subscribers.
        for key, sub in subs:
            if not sub.try_put(payload):
                _log.warning(
                    "cluster ws: subscriber %s slow, dropping", key,
                )
                try:
                    await sub.ws.close(code=1013, reason="Backpressure")
                except Exception:
                    pass
                async with self._lock:
                    self._subs.pop(key, None)
                await sub.close()

    @property
    def count(self) -> int:
        return len(self._subs)


_hub: Optional[ChangeHub] = None


def get_hub() -> ChangeHub:
    global _hub
    if _hub is None:
        _hub = ChangeHub()
    return _hub


def publish_change(event: dict[str, Any]) -> None:
    hub = get_hub()
    if hub.count == 0:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(hub.broadcast(event))
