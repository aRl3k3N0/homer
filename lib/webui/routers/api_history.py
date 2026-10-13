"""
History API: /api/history, /api/history/{id}, DELETE, purge.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.auth import PERM_HISTORY_VIEW, PERM_HISTORY_VIEW_ALL
from lib.webui.deps import Dependencies, WebUIState


def build_router(state: WebUIState, deps: Dependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/history",
                dependencies=[Depends(deps.require_perm(PERM_HISTORY_VIEW))])
    def api_history(request: Request,
                    user=Depends(deps.current_user),
                    view_user: Optional[str] = None,
                    command: Optional[str] = None,
                    limit: int = 100,
                    offset: int = 0):
        storage = deps.get_history()

        can_view_all = user.has_perm(PERM_HISTORY_VIEW_ALL)
        target = view_user if (can_view_all and view_user) else user.username

        entries = storage.list(user=target, command=command,
                               limit=limit, offset=offset)
        return [
            {
                "id": e.id,
                "user": e.user,
                "command": e.command,
                "args": e.args,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "finished_at": e.finished_at.isoformat() if e.finished_at else None,
                "exit_code": e.exit_code,
                "duration_ms": e.duration_ms,
                "client_ip": e.client_ip,
            }
            for e in entries
        ]

    @router.get("/api/history/{entry_id}",
                dependencies=[Depends(deps.require_perm(PERM_HISTORY_VIEW))])
    def api_history_entry(entry_id: str,
                          user=Depends(deps.current_user)):
        storage = deps.get_history()
        entry = storage.get(entry_id)
        if not entry:
            raise HTTPException(404, "Not found")
        if entry.user != user.username and not user.has_perm(PERM_HISTORY_VIEW_ALL):
            raise HTTPException(403, "Forbidden")
        return {
            "id": entry.id,
            "user": entry.user,
            "command": entry.command,
            "args": entry.args,
            "started_at": entry.started_at.isoformat() if entry.started_at else None,
            "finished_at": entry.finished_at.isoformat() if entry.finished_at else None,
            "exit_code": entry.exit_code,
            "duration_ms": entry.duration_ms,
            "output": entry.output,
            "input_log": entry.input_log,
            "client_ip": entry.client_ip,
            "user_agent": entry.user_agent,
        }

    @router.delete("/api/history/{entry_id}",
                   dependencies=[Depends(deps.require_perm(PERM_HISTORY_VIEW))])
    def api_history_delete(entry_id: str,
                           user=Depends(deps.current_user)):
        storage = deps.get_history()
        entry = storage.get(entry_id)
        if not entry:
            raise HTTPException(404)
        if entry.user != user.username and not user.has_perm(PERM_HISTORY_VIEW_ALL):
            raise HTTPException(403)
        storage.db.execute(
            f"DELETE FROM homer_console_history WHERE id = {storage._ph(0)}",
            [entry_id],
        )
        storage.db.commit()
        return {"deleted": entry_id}

    @router.post("/api/history/purge",
                 dependencies=[Depends(deps.require_perm(PERM_HISTORY_VIEW))])
    def api_history_purge(older: int = 86400 * 30):
        storage = deps.get_history()
        return {"purged": storage.purge_older_than(older)}

    return router
