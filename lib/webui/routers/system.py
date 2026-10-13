"""
System endpoints: /healthz, /metrics.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from lib.webui.deps import WebUIState
from lib.webui.schemas import HealthSchema


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

    return router
