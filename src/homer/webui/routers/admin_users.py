"""
User and role management for the Web UI.

HTML pages:
    GET  /admin/users           -- list users (with search & filter)
    GET  /admin/roles           -- list roles

JSON API (used by the page):
    GET    /api/admin/users                -- list
    GET    /api/admin/users/{username}     -- detail
    POST   /api/admin/users                -- create
    PATCH  /api/admin/users/{username}     -- update (display_name, email, password, enabled)
    DELETE /api/admin/users/{username}     -- delete
    GET    /api/admin/users/{username}/roles
    PUT    /api/admin/users/{username}/roles   -- replace roles
    GET    /api/admin/roles                -- list
    POST   /api/admin/roles                -- create
    PATCH  /api/admin/roles/{name}         -- update permissions
    DELETE /api/admin/roles/{name}         -- delete (non-builtin only)
    GET    /api/admin/permissions          -- available permission list
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from homer.auth import (
    PERM_ROLES_MANAGE, PERM_USERS_MANAGE,
    ALL_PERMISSIONS,
)
from homer.webui.deps import Dependencies, WebUIState


# ─────────── Pydantic schemas ───────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64,
                          pattern=r"^[a-zA-Z0-9_.\-]+$")
    password: Optional[str] = Field(None, min_length=1)
    display_name: str = ""
    email: str = ""
    provider: str = "local"
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    enabled: bool = True


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = Field(None, min_length=1)
    enabled: Optional[bool] = None


class UserRolesUpdate(BaseModel):
    roles: list[str]


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64,
                      pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = ""
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    display_name: Optional[str] = None
    permissions: Optional[list[str]] = None


# ─────────── Router ───────────

def build_router(state: WebUIState, deps: Dependencies, templates) -> APIRouter:
    router = APIRouter()
    store = state.auth_store

    # ═══════════════════════════════════════════════════════════════
    #  HTML pages
    # ═══════════════════════════════════════════════════════════════

    @router.get("/admin/users", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def admin_users_page(request: Request):
        return templates.TemplateResponse(
            request=request, name="admin_users.html",
            context={},
        )

    @router.get("/admin/roles", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_ROLES_MANAGE))])
    def admin_roles_page(request: Request):
        return templates.TemplateResponse(
            request=request, name="admin_roles.html",
            context={},
        )

    # ═══════════════════════════════════════════════════════════════
    #  Users API
    # ═══════════════════════════════════════════════════════════════

    @router.get("/api/admin/users",
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_list_users():
        users = store.list_users()
        return [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "email": u.email,
                "provider": u.provider,
                "enabled": u.enabled,
                "roles": u.roles,
            }
            for u in users
        ]

    @router.get("/api/admin/users/{username}",
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_get_user(username: str):
        u = store.get_user_by_name(username)
        if not u:
            raise HTTPException(404, "User not found")
        return {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "provider": u.provider,
            "enabled": u.enabled,
            "roles": u.roles,
        }

    @router.post("/api/admin/users",
                 dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_create_user(payload: UserCreate):
        if store.get_user_by_name(payload.username):
            raise HTTPException(409, f"User '{payload.username}' already exists")

        # Create with or without password (external providers don't need one)
        uid = store.create_user(
            payload.username,
            password=payload.password,
            display_name=payload.display_name,
            email=payload.email,
            provider=payload.provider,
        )
        # Assign roles
        for role in payload.roles or []:
            if not store.get_role(role):
                raise HTTPException(400, f"Unknown role: {role}")
            store.assign_role(uid, role)
        if not payload.enabled:
            store.set_enabled(payload.username, False)

        u = store.get_user(uid)
        return {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "provider": u.provider,
            "enabled": u.enabled,
            "roles": u.roles,
        }

    @router.patch("/api/admin/users/{username}",
                  dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_update_user(username: str, payload: UserUpdate,
                        current_user=Depends(deps.current_user)):
        u = store.get_user_by_name(username)
        if not u:
            raise HTTPException(404, "User not found")

        # Guard: do not disable the last admin
        if payload.enabled is False and "admin" in u.roles:
            if store.count_admins() <= 1:
                raise HTTPException(
                    400, "Cannot disable the last admin"
                )

        # Guard: do not disable yourself
        if payload.enabled is False and username == current_user.username:
            raise HTTPException(400, "You cannot disable your own account")

        ok = store.update_user(
            username,
            display_name=payload.display_name,
            email=payload.email,
            enabled=payload.enabled,
            password=payload.password,
        )
        if not ok:
            raise HTTPException(500, "Update failed")

        u = store.get_user_by_name(username)
        return {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "email": u.email,
            "provider": u.provider,
            "enabled": u.enabled,
            "roles": u.roles,
        }

    @router.delete("/api/admin/users/{username}",
                   dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_delete_user(username: str,
                        current_user=Depends(deps.current_user)):
        u = store.get_user_by_name(username)
        if not u:
            raise HTTPException(404, "User not found")

        if username == current_user.username:
            raise HTTPException(400, "You cannot delete your own account")

        if "admin" in u.roles and store.count_admins() <= 1:
            raise HTTPException(400, "Cannot delete the last admin")

        store.delete_user(username)
        return {"deleted": username}

    # ─── Roles per user ───

    @router.get("/api/admin/users/{username}/roles",
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_user_roles(username: str):
        u = store.get_user_by_name(username)
        if not u:
            raise HTTPException(404, "User not found")
        return {"roles": u.roles}

    @router.put("/api/admin/users/{username}/roles",
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_set_user_roles(username: str, payload: UserRolesUpdate,
                           current_user=Depends(deps.current_user)):
        u = store.get_user_by_name(username)
        if not u:
            raise HTTPException(404, "User not found")

        # Guard: removing your own admin role
        if (username == current_user.username
                and "admin" in u.roles
                and "admin" not in payload.roles):
            raise HTTPException(400, "You cannot remove your own admin role")

        # Guard: removing admin from the last admin
        if ("admin" in u.roles and "admin" not in payload.roles
                and store.count_admins() <= 1):
            raise HTTPException(400, "Cannot remove the last admin")

        for role in payload.roles:
            if not store.get_role(role):
                raise HTTPException(400, f"Unknown role: {role}")

        store.set_roles(u.id, payload.roles)
        return {"roles": payload.roles}

    # ═══════════════════════════════════════════════════════════════
    #  Roles API
    # ═══════════════════════════════════════════════════════════════

    @router.get("/api/admin/roles",
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_list_roles():
        return store.list_roles()

    @router.post("/api/admin/roles",
                 dependencies=[Depends(deps.require_perm(PERM_ROLES_MANAGE))])
    def api_create_role(payload: RoleCreate):
        if store.get_role(payload.name):
            raise HTTPException(409, f"Role '{payload.name}' already exists")
        # Validate permissions
        unknown = [p for p in payload.permissions if p not in ALL_PERMISSIONS]
        if unknown:
            raise HTTPException(400, f"Unknown permissions: {unknown}")
        store.upsert_role(
            payload.name,
            display_name=payload.display_name or payload.name,
            permissions=payload.permissions,
            builtin=False,
        )
        return store.get_role(payload.name)

    @router.patch("/api/admin/roles/{name}",
                  dependencies=[Depends(deps.require_perm(PERM_ROLES_MANAGE))])
    def api_update_role(name: str, payload: RoleUpdate):
        role = store.get_role(name)
        if not role:
            raise HTTPException(404, "Role not found")

        perms = payload.permissions if payload.permissions is not None \
            else role["permissions"]
        unknown = [p for p in perms if p not in ALL_PERMISSIONS]
        if unknown:
            raise HTTPException(400, f"Unknown permissions: {unknown}")

        store.upsert_role(
            name,
            display_name=payload.display_name or role["display_name"],
            permissions=perms,
            builtin=role["builtin"],
        )
        return store.get_role(name)

    @router.delete("/api/admin/roles/{name}",
                   dependencies=[Depends(deps.require_perm(PERM_ROLES_MANAGE))])
    def api_delete_role(name: str):
        role = store.get_role(name)
        if not role:
            raise HTTPException(404, "Role not found")
        if role["builtin"]:
            raise HTTPException(400, "Cannot delete a builtin role")
        ok = store.delete_role(name)
        if not ok:
            raise HTTPException(400, "Delete failed")
        return {"deleted": name}

    @router.get("/api/admin/permissions",
                dependencies=[Depends(deps.require_perm(PERM_USERS_MANAGE))])
    def api_list_permissions():
        return sorted(ALL_PERMISSIONS)

    return router
