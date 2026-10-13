"""
HTML pages:
    /                    -- job queue
    /jobs/{id}           -- job detail
    /history             -- console command history
    /history/{id}        -- history entry detail
    /logs                -- log viewer
    /console             -- interactive console
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from lib.auth import (
    PERM_CONSOLE_USE,
    PERM_HISTORY_VIEW,
    PERM_JOBS_VIEW,
    PERM_LOGS_VIEW,
    PERM_HISTORY_VIEW_ALL,
)
from lib.webui.deps import Dependencies, WebUIState, job_to_dict


def build_router(state: WebUIState, deps: Dependencies, templates) -> APIRouter:
    router = APIRouter()

    # ─────────── Jobs list ───────────

    @router.get("/", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_JOBS_VIEW))])
    def index(request: Request,
              status: Optional[str] = None,
              q: Optional[str] = None):
        storage = deps.get_storage()
        try:
            jobs = storage.list(status=status or None, limit=200)
            stats = storage.stats()
            jobs_dict = [job_to_dict(j) for j in jobs]
            if q:
                ql = q.lower()
                jobs_dict = [
                    j for j in jobs_dict
                    if ql in j["command"].lower() or ql in str(j["args"]).lower()
                ]
        finally:
            storage.close()

        return templates.TemplateResponse(
            request=request, name="index.html",
            context={
                "jobs": jobs_dict,
                "stats": stats,
                "filter_status": status,
                "query": q or "",
                "statuses": [
                    "pending", "running", "done",
                    "failed", "canceled", "timeout",
                ],
            },
        )

    # ─────────── Job detail ───────────

    @router.get("/jobs/{job_id}", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_JOBS_VIEW))])
    def job_detail(request: Request, job_id: int):
        storage = deps.get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            children = [
                j for j in storage.list(limit=500)
                if j.parent_job_id == job_id
            ]
            children_dict = [job_to_dict(j) for j in children]
        finally:
            storage.close()

        return templates.TemplateResponse(
            request=request, name="job.html",
            context={"job": job_to_dict(job), "children": children_dict},
        )

    # ─────────── History ───────────

    @router.get("/history", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_HISTORY_VIEW))])
    def history_page(request: Request,
                     user=Depends(deps.current_user),
                     view_user: Optional[str] = None,
                     command: Optional[str] = None,
                     limit: int = 100):
        storage = deps.get_history()

        can_view_all = user.has_perm(PERM_HISTORY_VIEW_ALL)

        # Determine whose history to show
        target_user: Optional[str]
        if can_view_all and view_user:
            if view_user == "__all__":  # спец. значение: показать всех
                target_user = None
            elif view_user:
                target_user = view_user
            else:
                target_user = user.username  # по умолчанию — своя
        else:
            # Without permission, ignore any view_user; show own history
            target_user = user.username

        entries = storage.list(user=target_user, command=command, limit=limit)

        # Distinct commands of the *target* user (not the current one)
        if target_user:
            commands = storage.distinct_commands(user=target_user)
        else:
            commands = storage.distinct_commands(user=None)

        # User list for the filter (only for those with view-all)
        all_users: list[str] = []
        if can_view_all:
            try:
                all_users = storage.distinct_users()
            except Exception:
                all_users = []

        return templates.TemplateResponse(
            request=request, name="history.html",
            context={
                "entries": entries,
                "commands": commands,
                "selected_command": command or "",
                "history_username": target_user or "(all)",
                "view_user": view_user or "",
                "can_view_all": can_view_all,
                "all_users": all_users,
                "self_username": user.username,
            },
        )

    @router.get("/history/{entry_id}", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_HISTORY_VIEW))])
    def history_detail(request: Request,
                       entry_id: str,
                       user=Depends(deps.current_user)):
        storage = deps.get_history()
        entry = storage.get(entry_id)
        if not entry:
            raise HTTPException(status_code=404)

        if entry.user != user.username and not user.has_perm(PERM_HISTORY_VIEW_ALL):
            raise HTTPException(status_code=403, detail="Forbidden")

        return templates.TemplateResponse(
            request=request, name="history_detail.html",
            context={"entry": entry},
        )

    # ─────────── Logs ───────────

    @router.get("/logs", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_LOGS_VIEW))])
    def logs_index(request: Request,
                   command: Optional[str] = None,
                   date_: Optional[str] = None,
                   level: Optional[str] = None,
                   grep: Optional[str] = None,
                   limit: int = 500):
        reader = deps.get_logs_reader()
        files = reader.list_files()
        commands = reader.list_commands()
        entries = []

        target_command = command
        target_date = date_

        if not target_command and files:
            target_command = files[0].command
            target_date = target_date or files[0].date.isoformat()

        if target_command and target_date:
            try:
                entries = reader.read(
                    target_command, target_date,
                    level=level, grep=grep, limit=limit,
                )
            except Exception:
                entries = []

        return templates.TemplateResponse(
            request=request, name="logs.html",
            context={
                "files": files,
                "commands": commands,
                "entries": entries,
                "selected_command": target_command,
                "selected_date": target_date,
                "selected_level": level or "",
                "grep": grep or "",
                "limit": limit,
            },
        )

    # ─────────── Console ───────────

    @router.get("/console", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_CONSOLE_USE))])
    def console_page(request: Request):
        from lib.command_loader import CommandLoader
        from lib.commands import BUILTIN_COMMANDS

        loader = CommandLoader(state.root_dir / "commands",
                               root_dir=state.root_dir)
        user_commands = loader.metadata()

        all_commands: dict[str, dict] = {}
        for name, meta in user_commands.items():
            all_commands[name] = meta
        for name, info in BUILTIN_COMMANDS.items():
            all_commands.setdefault(name, {
                "description": info.get("description", ""),
                "usage": "",
                "params": {},
                "examples": [],
                "hidden": False,
                "source": info.get("source", "builtin"),
            })

        allowed = state.config.get("webui.console.allow_commands") or []
        denied = state.config.get("webui.console.deny_commands") or []

        platform_hidden = {"webui", "shell"}

        visible = {}
        for name, meta in all_commands.items():
            if not allowed and name in denied:
                continue
            if allowed and name not in allowed:
                continue
            if meta.get("hidden"):
                continue
            if name.startswith("_"):
                continue
            if name in platform_hidden:
                continue
            visible[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "usage": meta.get("usage", ""),
                "params": meta.get("params", {}),
                "examples": meta.get("examples", []),
                "source": meta.get("source", "user"),
            }

        def _sort_key(item):
            _, meta = item
            return (meta["source"].startswith("builtin"), item[0].lower())

        visible_sorted = dict(sorted(visible.items(), key=_sort_key))

        return templates.TemplateResponse(
            request=request, name="console.html",
            context={"commands": visible_sorted},
        )

    return router
