"""
WS client: connect to primary and receive live updates.

Uses websockets (pip install websockets).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

try:
    import websockets
    _HAS_WS = True
except ImportError:
    _HAS_WS = False

_log = logging.getLogger("homer.cluster.ws_client")


class ClusterClient:
    def __init__(self, url: str, cluster_files, token: Optional[str] = None):
        self.url = url
        self.cluster_files = cluster_files
        self.token = token

    async def run(self):
        if not _HAS_WS:
            _log.warning("websockets not installed; cluster WS disabled")
            return
        while True:
            try:
                await self._connect_once()
            except Exception as e:
                _log.warning("cluster ws: %s; reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def _connect_once(self):
        url = self.url
        if self.token:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}token={self.token}"

        async with websockets.connect(url) as ws:
            _log.info("cluster ws: connected to %s", self.url)
            while True:
                msg = await ws.recv()
                if msg == "pong":
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                await self._on_message(data)

    async def _on_message(self, data: dict):
        t = data.get("type")
        if t == "file.changed":
            self.cluster_files._apply_change({
                "category": data["category"],
                "rel_path": data["path"],
                "action": "write",
            })
        elif t == "file.deleted":
            self.cluster_files._apply_change({
                "category": data["category"],
                "rel_path": data["path"],
                "action": "delete",
            })
        elif t in ("config.changed", "config.value.created",
                   "config.deleted", "config.section.created",
                   "config.section.deleted", "config.renamed",
                   "langs.changed", "langs.synced",
                   "history.rollback"):
            # Pull whatever sources may have changed
            try:
                self.cluster_files.initial_sync()
            except Exception:
                pass
