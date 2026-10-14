"""
Cluster join API.

    POST /api/cluster/join  -- register a new node with this primary

Payload:
    {
      "hostname": "worker1.example.com",
      "ip": "10.0.0.11",
      "role": "worker",
      "version": "1.0.1",
      "api_url": "http://10.0.0.11:8081",
      "meta": {"pid": 12345, "port": 8081}
    }

Response:
    {
      "node_id": "a1b2c3d4-...",
      "ws_url": "ws://primary.example.com:8081/ws/cluster",
      "ws_token": "secret",
      "primary_id": "primary-node-id",
      "ttl_seconds": 60,
      "heartbeat_seconds": 15
    }
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Any, Optional
import uuid

from lib.cluster.nodes import NodeRegistry
from lib.webui.deps import WebUIState


class JoinReq(BaseModel):
    hostname: str
    ip: Optional[str] = None
    role: str = "worker"
    version: Optional[str] = None
    api_url: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
    node_id: Optional[str] = None     # if already known


def build_router(state: WebUIState) -> APIRouter:
    router = APIRouter()

    @router.post("/api/cluster/join")
    def cluster_join(req: JoinReq, request: Request):
        # ─── Optional shared-secret protection
        expected_token = state.config.get("cluster.join_token")
        if expected_token:
            header = request.headers.get("x-cluster-token", "")
            if header != expected_token:
                raise HTTPException(401, "Invalid join token")

        # ─── Only primary accepts joins
        local_role = state.config.get("cluster.role")
        if local_role not in ("primary", None):
            # If election is used, only the current primary
            nr = getattr(state, "node_registry", None)
            if nr is not None and nr.role != "primary":
                raise HTTPException(
                    409, "This node is not primary; join the primary instead"
                )

        # ─── Generate / reuse node_id
        node_id = req.node_id or str(uuid.uuid4())

        cfg = state.config
        ttl = int(cfg.get("cluster.ttl_seconds", 60))

        reg = NodeRegistry(cfg, node_id=node_id, ttl_seconds=ttl)
        try:
            reg.role = req.role
            reg.meta = dict(req.meta or {})
            if req.api_url:
                reg.meta["api_url"] = req.api_url
            reg.register()
        finally:
            reg.db.close()

        # ─── Advertise WS endpoint
        public_url = cfg.get("webui.public_url") or ""
        ws_base = cfg.get("cluster.public_ws_url")
        if not ws_base:
            if public_url:
                ws_base = public_url.replace("http://", "ws://") \
                                   .replace("https://", "wss://")
            else:
                ws_base = "ws://localhost:8081"
        ws_url = ws_base.rstrip("/") + "/ws/cluster"

        return {
            "node_id": node_id,
            "ws_url": ws_url,
            "ws_token": cfg.get("cluster.ws_token"),
            "primary_id": getattr(state, "node_registry", None) and
                          state.node_registry.node_id,
            "ttl_seconds": ttl,
            "heartbeat_seconds": int(cfg.get("cluster.heartbeat_seconds", 15)),
        }

    return router
