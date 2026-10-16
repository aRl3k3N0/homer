"""
System endpoints: /healthz, /metrics.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from homer.webui.deps import WebUIState
from homer.webui.schemas import HealthSchema


def build_router(state: WebUIState) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthSchema, tags=["system"])
    def healthz():
        try:
            storage = state.get_storage()
            storage.stats()
            storage.close()
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=503)

    @router.get("/metrics", tags=["system"], response_class=Response)
    def metrics():
        try:
            from lib.metrics import metrics_endpoint
        except ImportError:
            return Response(content=b"# metrics module not available\n",
                            media_type="text/plain")
        body, ctype = metrics_endpoint()
        return Response(content=body, media_type=ctype)

    @router.get("/api/diagnostics")
    def api_diagnostics():
        """
        Public diagnostics endpoint, callable by other nodes.
        Not HTML, not protected by auth (assumes internal network).
        If you want to protect it, use cluster.ws_token as a Bearer token.
        """
        from homer.cluster.diagnostics import collect_diagnostics
        from homer.cluster.ws_server import get_hub

        return collect_diagnostics(
            state.config,
            state.config.paths,
            logger=state.logger,
            node_registry=getattr(state, "node_registry", None),
            cluster_files=getattr(state, "cluster_files", None),
            ws_hub=get_hub(),
        )

    return router
