"""
FastAPI application factory for the Web UI.

All routes live in `lib/webui/routers/`. This module wires everything:

    1. Load config and paths.
    2. Build templates (core + project + plugins).
    3. Build WebUIState and Dependencies.
    4. Mount routers.
    5. Register middleware (auth-state, i18n).
    6. Startup/shutdown hooks and OpenAPI customization.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from lib.i18n import get_i18n
from lib.webui.deps import Dependencies, WebUIState, bind_locale
from lib.webui.routers import (
    admin_users,
    api_history,
    api_jobs,
    api_logs,
    auth_pages,
    editor,
    pages,
    system,
    ws,
    profile
)
from lib.webui.templating import CORE_TEMPLATES_DIR, build_templates
from lib.webui.ws import get_hub


log = logging.getLogger("homer.webui")

TAGS_METADATA = [
    {"name": "jobs", "description": "Job queue operations."},
    {"name": "stats", "description": "Queue statistics."},
    {"name": "actions", "description": "Job actions: cancel, retry, purge."},
    {"name": "system", "description": "Health and metrics."},
]


def create_app(config, root_dir=None, auth=None, enable_docs=True, logger=None):
    """
    Build the FastAPI application.

    `auth` is accepted for backward compatibility but ignored:
    authentication is handled by AuthManager (see WebUIState).
    """
    if not config.get("webui.enabled", True):
        stub = FastAPI()

        @stub.get("/")
        def _disabled():
            return {"ok": False,
                    "error": "Web UI disabled in config.yml (webui.enabled=false)"}

        return stub

    root_dir = Path(root_dir) if root_dir else Path(".").resolve()

    app = FastAPI(
        title="Homer Queue API",
        description="REST API for monitoring and controlling the Homer queue.",
        version=config.get("app.version", "1.0.0"),
        contact={"name": "Homer",
                 "url": config.get("webui.contact_url", "") or ""},
        license_info={"name": "MIT",
                      "url": "https://opensource.org/licenses/MIT"},
        openapi_tags=TAGS_METADATA,
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
    )

    # ─────────── Static (core) ───────────
    static_dir = CORE_TEMPLATES_DIR.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)),
                  name="static")

    # ─────────── Plugins ───────────
    from lib.plugins import get_manager
    plugin_mgr = get_manager()

    for p in plugin_mgr.list():
        sd = getattr(p, "static_dir", None)
        if sd:
            try:
                app.mount(
                    f"/static/plugins/{p.name}",
                    StaticFiles(directory=str(sd)),
                    name=f"plugin-static-{p.name}",
                )
            except Exception as e:
                log.warning("plugin static mount failed for %s: %s", p.name, e)

    # ─────────── Templates ───────────
    project_templates: Optional[Path] = None
    try:
        from lib.paths import Paths
        if getattr(config, "paths", None) is not None:
            paths = config.paths
        else:
            paths = Paths.from_config(config, root_dir / "config.yml")
            config.paths = paths       # cache for other components
        project_templates = paths.templates_dir
    except Exception as e:
        log.warning("Could not resolve project templates: %s", e)
        project_templates = None

    plugin_templates: list[Path] = []
    try:
        for p in plugin_mgr.list():
            td = getattr(p, "templates_dir", None)
            if td:
                plugin_templates.append(Path(td))
    except Exception as e:
        log.warning("Could not enumerate plugin template dirs: %s", e)

    try:
        templates = build_templates(project_templates, plugin_templates)
    except Exception as e:
        raise RuntimeError(f"Failed to build Jinja templates: {e}") from e

    # ─────────── State & dependencies ───────────
    state = WebUIState(config, root_dir, logger=logger)
    # Preserve cluster_files if the caller attached one to config
    if getattr(config, "cluster_files", None) is not None \
            and getattr(state, "cluster_files", None) is None:
        state.cluster_files = config.cluster_files

    deps = Dependencies(state)

    # ─────────── Routers ───────────
    # Public: no auth required
    app.include_router(
        auth_pages.build_router(state, templates),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(system.build_router(state))

    # Protected: apply locale binding + auth per router
    app.include_router(
        pages.build_router(state, deps, templates),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(
        api_jobs.build_router(state, deps),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(
        api_history.build_router(state, deps),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(
        api_logs.build_router(state, deps),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(
        admin_users.build_router(state, deps, templates),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(
        editor.build_router(state, deps, templates),
        dependencies=[Depends(bind_locale)],
    )
    app.include_router(
        profile.build_router(state, deps, templates),
        dependencies=[Depends(bind_locale)],
    )

    # WebSocket router: no bind_locale (no templates rendered here)
    app.include_router(ws.build_router(state))

    # ═══════════════════════════════════════════════════════════════
    #  Middleware
    # ═══════════════════════════════════════════════════════════════
    #
    # Starlette executes middleware in reverse order of declaration:
    # the LAST declared is the outermost (runs first).
    # We want: auth_state (outer) → i18n (inner) → routers.
    # So declare i18n first, then auth_state.

    @app.middleware("http")
    async def i18n_middleware(request: Request, call_next):
        i18n = get_i18n()

        # 1) user.locale (set by auth_state_middleware)
        user = getattr(request.state, "user", None)
        locale = None
        if user is not None and getattr(user, "locale", None):
            locale = user.locale

        # 2) Accept-Language (anonymous fallback)
        if not locale:
            locale = _parse_accept_language(
                request.headers.get("accept-language", "")
            )

        # 3) default from config
        if not locale or locale not in i18n.available_locales():
            locale = i18n.default_locale

        if locale not in i18n.available_locales():
            locale = i18n.fallback_locale

        request.state.locale = locale
        response = await call_next(request)

        # No Set-Cookie: locale is stored in the user profile, not in a cookie.
        return response

    @app.middleware("http")
    async def auth_state_middleware(request: Request, call_next):
        exempt = ("/login", "/logout", "/healthz", "/metrics")
        if request.url.path in exempt:
            request.state.user = None
            return await call_next(request)
        try:
            request.state.user = state.user_from_request(request)
        except Exception:
            request.state.user = None
        return await call_next(request)

    # ═══════════════════════════════════════════════════════════════
    #  Publisher for /ws
    # ═══════════════════════════════════════════════════════════════

    hub = get_hub()

    @app.on_event("startup")
    async def _startup_publisher():
        from lib.webui.deps import job_to_dict

        async def publisher():
            last_snapshot: dict[int, str] = {}
            last_stats: dict = {}
            while True:
                try:
                    storage = state.get_storage()
                    try:
                        jobs = storage.list(limit=500)
                        stats = storage.stats()
                    finally:
                        storage.close()

                    current = {j.id: j.status for j in jobs}

                    for j in jobs:
                        if j.id not in last_snapshot:
                            await hub.broadcast({"type": "job.created",
                                                 "job": job_to_dict(j)})
                        elif last_snapshot[j.id] != j.status:
                            await hub.broadcast({"type": "job.updated",
                                                 "job": job_to_dict(j)})

                    for jid in set(last_snapshot) - set(current):
                        await hub.broadcast({"type": "job.removed",
                                             "job_id": jid})

                    if stats != last_stats:
                        await hub.broadcast({"type": "stats.updated",
                                             "stats": stats})
                        last_stats = stats

                    last_snapshot = current
                except Exception as e:
                    if logger is not None:
                        try:
                            logger.warning(f"publisher error: {e}",
                                           command="webui")
                        except Exception:
                            pass
                await asyncio.sleep(2)

        app.state._publisher_task = asyncio.create_task(publisher())

    @app.on_event("shutdown")
    async def _shutdown_publisher():
        t = getattr(app.state, "_publisher_task", None)
        if t:
            t.cancel()
        try:
            state.close()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    #  OpenAPI
    # ═══════════════════════════════════════════════════════════════

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=TAGS_METADATA,
        )
        schema["servers"] = [
            {"url": config.get("webui.public_url", "/"),
             "description": "Current server"},
        ]
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "BasicAuth"
        ] = {"type": "http", "scheme": "basic"}
        schema["security"] = [{"BasicAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi

    return app


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _parse_accept_language(header: str) -> Optional[str]:
    if not header:
        return None
    for part in header.split(","):
        code = part.split(";")[0].strip()
        if not code:
            continue
        lang = code.split("-")[0].lower()
        if lang:
            return lang
    return None
