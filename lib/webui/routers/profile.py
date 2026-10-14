"""
User profile page and API.

Allows the current user to change:
    - display name
    - email
    - password
    - preferred locale (interface language)

Admin-level actions (enable/disable, roles) are on /admin/users.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from lib.i18n import get_i18n
from lib.webui.deps import Dependencies, WebUIState


class ProfileUpdateReq(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = Field(None, min_length=1)
    locale: Optional[str] = None


def build_router(state: WebUIState, deps: Dependencies, templates) -> APIRouter:
    router = APIRouter()
    store = state.auth_store

    # ─────────── HTML page ───────────

    @router.get("/profile", response_class=HTMLResponse)
    def profile_page(request: Request):
        user = deps.current_user(request)
        i18n = get_i18n()
        return templates.TemplateResponse(
            request=request, name="profile.html",
            context={
                "user": user,
                "locales": i18n.available_locales(),
            },
        )

    # ─────────── API ───────────

    @router.get("/api/profile")
    def api_profile_get(request: Request):
        user = deps.current_user(request)
        return {
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "locale": user.locale,
            "provider": user.provider,
            "roles": user.roles,
        }

    @router.put("/api/profile")
    def api_profile_update(req: ProfileUpdateReq, request: Request):
        user = deps.current_user(request)

        # Password change requires the current password for local users
        if req.new_password:
            if user.provider == "local":
                if not req.current_password:
                    raise HTTPException(400, "Current password is required")
                if not store.verify_credentials(user.username,
                                                req.current_password):
                    raise HTTPException(400, "Current password is incorrect")

        # Validate locale against available locales
        locale = req.locale
        if locale is not None:
            i18n = get_i18n()
            if locale and locale not in i18n.available_locales():
                raise HTTPException(400, f"Unknown locale: {locale}")

        ok = store.update_user(
            user.username,
            display_name=req.display_name,
            email=req.email,
            password=req.new_password,
            locale=locale,
        )
        if not ok:
            raise HTTPException(500, "Update failed")

        # Return fresh data
        fresh = store.get_user_by_name(user.username)
        return {
            "username": fresh.username,
            "display_name": fresh.display_name,
            "email": fresh.email,
            "locale": fresh.locale,
            "roles": fresh.roles,
        }

    return router
