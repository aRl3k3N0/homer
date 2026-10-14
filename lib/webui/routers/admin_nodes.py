"""
Nodes management: /admin/nodes page + JSON API.

    GET    /admin/nodes                  -- HTML page
    GET    /api/admin/nodes              -- list of nodes
    GET    /api/admin/nodes/{id}         -- node detail
    POST   /api/admin/nodes/{id}/role    -- set role
    POST   /api/admin/nodes/{id}/shutdown -- request soft-stop
    POST   /api/admin/nodes/{id}/ping    -- health check via HTTP
    DELETE /api/admin/nodes/{id}         -- remove node record
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from lib.auth import PERM_SYSTEM_ADMIN, PERM_SYSTEM_VIEW
from lib.cluster.nodes import NodeRegistry, Node
from lib.webui.deps import Dependencies, WebUIState
from lib.cluster.diagnostics import collect_diagnostics
from lib.cluster.ws_server import get_hub as get_ws_hub


class RoleUpdateReq(BaseModel):
    role: str  # 'primary' | 'worker' | 'read-only'

class RestartReq(BaseModel):
    mode: str = "soft"  # 'soft' | 'hard'

def build_router(state: WebUIState, deps: Dependencies, templates) -> APIRouter:
    router = APIRouter()

    def _registry() -> NodeRegistry:
        return NodeRegistry(
            state.config,
            node_id="admin-view",  # ephemeral, only used to read
            ttl_seconds=int(state.config.get("cluster.ttl_seconds", 60)),
        )

    # ─────────── HTML ───────────

    @router.get("/admin/nodes", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_SYSTEM_VIEW))])
    def admin_nodes_page(request: Request):
        return templates.TemplateResponse(
            request=request, name="admin_nodes.html", context={},
        )

    # ─────────── API ───────────

    @router.get("/api/admin/nodes",
                dependencies=[Depends(deps.require_perm(PERM_SYSTEM_VIEW))])
    def api_list_nodes(include_dead: bool = False):
        reg = _registry()
        nodes = reg.list_nodes(only_alive=not include_dead)
        try:
            return [
                {
                    "id": n.id,
                    "hostname": n.hostname,
                    "ip": n.ip,
                    "started_at": n.started_at.isoformat() if n.started_at else None,
                    "last_seen": n.last_seen.isoformat() if n.last_seen else None,
                    "role": n.role,
                    "version": n.version,
                    "meta": n.meta,
                    "uptime_seconds": (
                        (datetime.now() - n.started_at).total_seconds()
                        if n.started_at else None
                    ),
                }
                for n in nodes
            ]
        finally:
            reg.db.close()

    @router.get("/api/admin/nodes/{node_id}",
                dependencies=[Depends(deps.require_perm(PERM_SYSTEM_VIEW))])
    def api_node_detail(node_id: str):
        reg = _registry()
        try:
            nodes = reg.list_nodes(only_alive=False)
            for n in nodes:
                if n.id == node_id:
                    return {
                        "id": n.id,
                        "hostname": n.hostname,
                        "ip": n.ip,
                        "started_at": n.started_at.isoformat() if n.started_at else None,
                        "last_seen": n.last_seen.isoformat() if n.last_seen else None,
                        "role": n.role,
                        "version": n.version,
                        "meta": n.meta,
                    }
        finally:
            reg.db.close()
        raise HTTPException(404, "Node not found")

    @router.post("/api/admin/nodes/{node_id}/role",
                 dependencies=[Depends(deps.require_perm(PERM_SYSTEM_ADMIN))])
    def api_set_node_role(node_id: str, req: RoleUpdateReq):
        if req.role not in ("primary", "worker", "read-only"):
            raise HTTPException(400, "role must be primary|worker|read-only")
        reg = _registry()
        try:
            reg.db.execute(
                f"UPDATE homer_nodes SET role = {reg._ph(0)} "
                f"WHERE id = {reg._ph(1)}",
                [req.role, node_id],
            )
            reg.db.commit()
            # Publish change to homer_commands so the node itself picks it up
            _publish_command(reg, node_id, "set-role", {"role": req.role})
        finally:
            reg.db.close()
        return {"id": node_id, "role": req.role}

    @router.post("/api/admin/nodes/{node_id}/shutdown",
                 dependencies=[Depends(deps.require_perm(PERM_SYSTEM_ADMIN))])
    def api_shutdown_node(node_id: str):
        reg = _registry()
        try:
            reg.db.execute(
                f"UPDATE homer_nodes SET shutdown = {reg._ph(0)} "
                f"WHERE id = {reg._ph(1)}",
                [reg._bool(True), node_id],
            )
            reg.db.commit()
            _publish_command(reg, node_id, "shutdown", {})
        finally:
            reg.db.close()
        return {"id": node_id, "shutdown": True}

    @router.post("/api/admin/nodes/{node_id}/ping",
                 dependencies=[Depends(deps.require_perm(PERM_SYSTEM_VIEW))])
    def api_ping_node(node_id: str):
        reg = _registry()
        try:
            nodes = reg.list_nodes(only_alive=False)
            node = next((n for n in nodes if n.id == node_id), None)
            if not node:
                raise HTTPException(404, "Node not found")
            url = node.meta.get("api_url") or (
                f"http://{node.ip}:{node.meta.get('port', 8081)}"
            )
            ok, message = _http_get(f"{url}/healthz")
            return {"id": node_id, "url": url, "ok": ok, "message": message}
        finally:
            reg.db.close()

    @router.delete("/api/admin/nodes/{node_id}",
                   dependencies=[Depends(deps.require_perm(PERM_SYSTEM_ADMIN))])
    def api_delete_node(node_id: str):
        reg = _registry()
        try:
            reg.db.execute(
                f"DELETE FROM homer_nodes WHERE id = {reg._ph(0)}",
                [node_id],
            )
            reg.db.commit()
        finally:
            reg.db.close()
        return {"deleted": node_id}

    @router.get("/api/admin/nodes/{node_id}/diagnostics",
                dependencies=[Depends(deps.require_perm(PERM_SYSTEM_VIEW))])
    def api_node_diagnostics(node_id: str):
        """
        Get diagnostics from a node.

        If node_id is this node, run diagnostics locally.
        Otherwise, try HTTP GET to remote <node.meta.api_url>/api/diagnostics.
        """
        reg = _registry()
        try:
            nodes = reg.list_nodes(only_alive=False)
            node = next((n for n in nodes if n.id == node_id), None)
            if not node:
                raise HTTPException(404, "Node not found")
        finally:
            reg.db.close()

        # Local?
        local_id = state.config.get("cluster.node_id")
        if local_id and local_id == node_id:
            return collect_diagnostics(
                state.config,
                state.config.paths,
                logger=state.logger,
                node_registry=state.node_registry,
                cluster_files=state.cluster_files,
                ws_hub=get_ws_hub(),
            )

        # Remote HTTP
        api_url = node.meta.get("api_url")
        if not api_url:
            ip = node.ip or "127.0.0.1"
            port = node.meta.get("port", 8081)
            api_url = f"http://{ip}:{port}"

        url = f"{api_url.rstrip('/')}/api/diagnostics"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                body = r.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except Exception as e:
            raise HTTPException(502, f"Remote diagnostics failed: {e}")

    @router.post("/api/admin/nodes/{node_id}/restart",
                 dependencies=[Depends(deps.require_perm(PERM_SYSTEM_ADMIN))])
    def api_restart_node(node_id: str, req: RestartReq,
                         user=Depends(deps.current_user)):
        if req.mode not in ("soft", "hard"):
            raise HTTPException(400, "mode must be soft|hard")

        reg = _registry()
        try:
            nodes = reg.list_nodes(only_alive=False)
            node = next((n for n in nodes if n.id == node_id), None)
            if not node:
                raise HTTPException(404, "Node not found")
        finally:
            reg.db.close()

        local_id = state.config.get("cluster.node_id")

        # ─── Local restart ───
        if local_id and local_id == node_id:
            import os
            import signal
            import threading
            import time

            def _do_restart():
                time.sleep(0.5)  # give the HTTP response time to flush
                try:
                    if req.mode == "hard":
                        os.kill(os.getpid(), signal.SIGKILL)
                    else:
                        os.kill(os.getpid(), signal.SIGTERM)
                except Exception:
                    pass

            t = threading.Thread(target=_do_restart, daemon=True)
            t.start()

            state.logger.warning(
                f"node: restarting (local, mode={req.mode}) by {user.username}",
                command="cluster",
            )
            return {"id": node_id, "mode": req.mode, "local": True}

        # ─── Remote restart via node command queue ───
        _publish_command(reg, node_id, "restart", {"mode": req.mode})
        return {"id": node_id, "mode": req.mode, "local": False}

    return router


def _http_get(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read(200).decode("utf-8", errors="replace")
            return r.status == 200, f"HTTP {r.status}: {body}"
    except Exception as e:
        return False, str(e)


def _publish_command(reg: NodeRegistry, node_id: str, action: str,
                     payload: dict):
    """
    Write a control command into a small queue table. Each node polls
    it and acts on its own id.
    """
    import json as _json
    try:
        reg.db.execute(
            f"INSERT INTO homer_node_commands "
            f"(node_id, action, payload, created_at) "
            f"VALUES ({reg._ph(0)}, {reg._ph(1)}, {reg._ph(2)}, {reg._ph(3)})",
            [node_id, action, _json.dumps(payload), datetime.now()],
        )
        reg.db.commit()
    except Exception:
        pass
