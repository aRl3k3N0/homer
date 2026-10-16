"""
Shared dependencies for Web UI routers.

Everything stateful lives here so routers stay thin:
    - WebUIState          -- long-lived objects (auth, storage, etc.)
    - Dependencies        -- Depends factories bound to a WebUIState
    - job_to_dict         -- canonical serialization of a QueueJob
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPBasic
from contextlib import contextmanager
from homer.auth import AuthStore, User
from homer.auth.manager import AuthManager
from homer.queue import QueueStorage
from .history import HistoryStorage
from .logs_reader import LogsReader


class WebUIState:
    """
    Holds every long-lived object a router needs.
    Constructed once in create_app() and passed to routers.
    """

    def __init__(self, config, root_dir: Path, logger=None):
        self.config = config
        self.root_dir = Path(root_dir)
        self.logger = logger

        # Auth
        self.auth_store = AuthStore(config)
        self.auth_manager = AuthManager(config, self.auth_store)

        # Cookie settings
        self.session_cookie = config.get("webui.auth.cookie_name", "homer_session")
        self.session_lifetime = int(config.get("webui.auth.session_lifetime", 86400))
        self.auth_mode = config.get("webui.auth.mode", "session")
        self.basic_enabled = bool(config.get("webui.auth.basic_enabled", True))

        self.basic_security = HTTPBasic(auto_error=False)

        # Logs
        from homer.core.paths import log_dir
        self.logs_reader = LogsReader(log_dir(config, self.root_dir))

        # History (lazy)
        self._history: Optional[HistoryStorage] = None

    # ─────────── Factories ───────────

    def get_storage(self) -> QueueStorage:
        return QueueStorage(self.config)

    def get_history(self) -> HistoryStorage:
        if self._history is None:
            self._history = HistoryStorage(self.config)
        return self._history

    def close(self) -> None:
        if self._history is not None:
            try:
                self._history.close()
            except Exception:
                pass
            self._history = None

    # ─────────── Authentication ───────────

    def user_from_request(self, request: Request) -> Optional[User]:
        # 1) Cookie session
        sid = request.cookies.get(self.session_cookie)
        if sid:
            u = self.auth_manager.user_by_session(sid)
            if u:
                return u

        # 2) HTTP Basic
        if self.auth_mode in ("basic", "both") or self.basic_enabled:
            header = request.headers.get("authorization", "")
            if header.lower().startswith("basic "):
                try:
                    raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
                    username, _, password = raw.partition(":")
                    pair = self.auth_manager.authenticate(
                        username, password,
                        ip=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                    )
                    if pair:
                        return pair[0]
                except Exception:
                    pass

        # 3) SSO (Kerberos / header)
        pair = self.auth_manager.authenticate_sso(request)
        if pair:
            return pair[0]

        return None

    def user_from_ws(self, websocket: WebSocket) -> Optional[User]:
        sid = websocket.cookies.get(self.session_cookie)
        if sid:
            u = self.auth_manager.user_by_session(sid)
            if u:
                return u

        q = websocket.query_params
        if q.get("user") and q.get("pass"):
            pair = self.auth_manager.authenticate(q["user"], q["pass"])
            if pair:
                return pair[0]
        return None


class Dependencies:
    """Bound dependencies for a single WebUIState."""

    def __init__(self, state: WebUIState):
        self.state = state

    # ─────────── User / permissions ───────────

    def current_user(self, request: Request) -> User:
        user = self.state.user_from_request(request)
        if not user:
            accept = request.headers.get("accept", "")
            wants_html = (
                "text/html" in accept
                and not request.url.path.startswith("/api/")
                and not request.url.path.startswith("/ws/")
            )
            if wants_html:
                raise HTTPException(
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                    headers={"Location": f"/login?next={request.url.path}"},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": 'Basic realm="Homer"'},
            )
        return user

    def require_perm(self, perm: str):
        def _dep(user: User = Depends(self.current_user)) -> User:
            if not user.has_perm(perm):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission required: {perm}",
                )
            return user

        return _dep

    # ─────────── Resources ───────────

    def get_storage(self) -> QueueStorage:
        return self.state.get_storage()

    def get_history(self) -> HistoryStorage:
        return self.state.get_history()

    def get_logs_reader(self) -> LogsReader:
        return self.state.logs_reader


def job_to_dict(job) -> dict:
    """Canonical dict representation of a QueueJob."""
    return {
        "id": job.id,
        "command": job.command,
        "args": job.args,
        "priority": job.priority,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "retry_delay": job.retry_delay,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "run_at": job.run_at.isoformat() if job.run_at else None,
        "exit_code": job.exit_code,
        "error": job.error,
        "result": (job.result or "")[:2000],
        "triggered_by": job.triggered_by,
        "parent_job_id": job.parent_job_id,
    }

def bind_locale(request: Request):
    """
    FastAPI dependency: set the i18n locale in the current context
    based on request.state.locale (set by middleware).

    Use as a dependency in routers that render templates or
    produce localized output:

        @router.get("/", dependencies=[Depends(bind_locale)])
        def index(request: Request): ...
    """
    from homer.i18n import get_i18n
    i18n = get_i18n()
    loc = getattr(request.state, "locale", None) or i18n.default_locale
    i18n.set_locale(loc)
    return loc
