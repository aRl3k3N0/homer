"""
Authentication pages: /login, /logout.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lib.webui.deps import WebUIState


def build_router(state: WebUIState, templates) -> APIRouter:
    router = APIRouter()

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/"):
        user = state.user_from_request(request)
        if user:
            return RedirectResponse(next or "/", status_code=303)
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"next": next, "error": None},
        )

    @router.post("/login")
    async def login_submit(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        next: str = Form("/"),
    ):
        username = username.strip()
        pair = state.auth_manager.authenticate(
            username, password,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        if not pair:
            return templates.TemplateResponse(
                request=request, name="login.html",
                context={"next": next, "error": "Invalid username or password"},
                status_code=401,
            )

        user, sid = pair
        resp = RedirectResponse(next or "/", status_code=303)
        resp.set_cookie(
            state.session_cookie, sid,
            max_age=state.session_lifetime,
            httponly=True,
            secure=bool(state.config.get("webui.auth.cookie_secure", False)),
            samesite="lax",
        )
        return resp

    @router.get("/logout")
    def logout(request: Request):
        sid = request.cookies.get(state.session_cookie)
        if sid:
            state.auth_manager.logout(sid)
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(state.session_cookie)
        return resp

    return router
