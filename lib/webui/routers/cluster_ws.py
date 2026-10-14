"""
Cluster WebSocket endpoint.

    /ws/cluster  -- server side, hosted by the primary node.
                    Subscribers (worker nodes) connect here to receive
                    a live stream of changes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from lib.cluster.ws_server import get_hub
from lib.webui.deps import WebUIState

_log = logging.getLogger("homer.cluster.ws")


def build_router(state: WebUIState) -> APIRouter:
    router = APIRouter()
    hub = get_hub()

    @router.websocket("/ws/cluster")
    async def ws_cluster(websocket: WebSocket):
        token = websocket.query_params.get("token")
        expected = state.config.get("cluster.ws_token")
        if expected and token != expected:
            await websocket.close(code=4401, reason="Unauthorized")
            return

        await hub.subscribe(websocket)
        try:
            await websocket.send_json({"type": "hello",
                                       "node_id": "primary"})
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unsubscribe(websocket)

    return router
    return router
