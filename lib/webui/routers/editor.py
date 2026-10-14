"""
Editor router.

Endpoints
---------

HTML:
    GET /editor                                -- landing (redirect by perm)
    GET /editor/config                         -- config registry UI
    GET /editor/files/{category}               -- file tree for a category
    GET /editor/files/{category}/{path}        -- code editor (CodeMirror)
    GET /editor/langs                          -- translations editor

Config registry API:
    GET    /api/editor/config/tree             -- sections tree (regedit style)
    GET    /api/editor/config/section          -- leaves of a section
    POST   /api/editor/config/section          -- create empty section
    DELETE /api/editor/config/section          -- delete empty section
    POST   /api/editor/config/value            -- create new value in a section
    POST   /api/editor/config/rename           -- rename value or section
    GET    /api/editor/config/export           -- export merged config as JSON
    POST   /api/editor/config/import           -- import (merge) config
    GET    /api/editor/config/{key_path}       -- read one entry
    PUT    /api/editor/config/{key_path}       -- set one entry
    DELETE /api/editor/config/{key_path}       -- delete one entry

File editor API:
    GET    /api/editor/tree/{category}         -- list files in a category
    GET    /api/editor/file/{category}         -- read one file
    PUT    /api/editor/file/{category}         -- write one file
    DELETE /api/editor/file/{category}         -- delete one file
    POST   /api/editor/mkdir/{category}        -- create directory
    POST   /api/editor/validate                -- syntax check (yaml/py/json)

Locks API:
    GET    /api/editor/lock                    -- list active locks
    POST   /api/editor/lock                    -- acquire lock
    POST   /api/editor/lock/refresh            -- refresh lock
    POST   /api/editor/lock/release            -- release lock

History API:
    GET    /api/editor/history                 -- list recent changes
    GET    /api/editor/history/{entry_id}      -- entry details
    GET    /api/editor/history/{entry_id}/diff -- unified diff
    POST   /api/editor/history/{entry_id}/rollback -- roll back

Translations API:
    GET    /api/editor/langs                   -- list locales
    GET    /api/editor/langs/{locale}          -- flat dictionary
    GET    /api/editor/langs/{locale}/tree     -- section tree
    GET    /api/editor/langs/{locale}/section  -- leaves of a section
    PUT    /api/editor/langs/{locale}          -- apply updates
    POST   /api/editor/langs/{locale}/sync     -- copy missing from fallback

IMPORTANT: route declaration order matters. Specific literal paths
(e.g. /tree, /section, /value, /rename) MUST come BEFORE the greedy
`{key_path:path}` routes.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from lib.auth import (
    PERM_EDITOR_VIEW,
    PERM_EDITOR_CONFIG,
    PERM_EDITOR_COMMANDS,
    PERM_EDITOR_PLUGINS,
    PERM_EDITOR_PLUGINS_ADMIN,
    PERM_EDITOR_LANGS,
    PERM_EDITOR_TEMPLATES,
    PERM_EDITOR_STATIC,
)
from lib.cluster.ws_server import publish_change          # ← new
from lib.editor.config_registry import ConfigRegistry, ConfigRegistryError
from lib.editor.files import (
    FileEditor, EditorError, PermissionDenied, ConflictError,
)
from lib.editor.history import EditorHistory
from lib.editor.locks import LockStore, LockError
from lib.i18n import get_i18n
from lib.webui.deps import Dependencies, WebUIState


# ═══════════════════════════════════════════════════════════════
#           Permission mapping
# ═══════════════════════════════════════════════════════════════

CATEGORY_PERM = {
    "config":    PERM_EDITOR_CONFIG,
    "commands":  PERM_EDITOR_COMMANDS,
    "plugins":   PERM_EDITOR_PLUGINS,
    "langs":     PERM_EDITOR_LANGS,
    "templates": PERM_EDITOR_TEMPLATES,
    "static":    PERM_EDITOR_STATIC,
    "email":     PERM_EDITOR_TEMPLATES,
}

PLUGIN_MANIFEST_SUFFIX = "plugin.json"


# ═══════════════════════════════════════════════════════════════
#           Pydantic schemas
# ═══════════════════════════════════════════════════════════════

class FileWriteReq(BaseModel):
    path: str
    content: str
    expected_checksum: Optional[str] = None
    create: bool = False


class FileDeleteReq(BaseModel):
    path: str


class MkdirReq(BaseModel):
    path: str


class LockReq(BaseModel):
    resource: str
    ttl: int = 300


class LockRefreshReq(BaseModel):
    resource: str
    token: str
    ttl: int = 300


class LockReleaseReq(BaseModel):
    resource: str
    token: str


class ConfigSetReq(BaseModel):
    value: Any
    expected_value: Any = None


class SectionCreateReq(BaseModel):
    path: str


class ValueCreateReq(BaseModel):
    path: str
    value: Any


class RenameReq(BaseModel):
    old_path: str
    new_path: str


class LangSetReq(BaseModel):
    updates: dict[str, Optional[str]]


class ValidateReq(BaseModel):
    category: str
    path: Optional[str] = None
    content: str


class ConfigImportReq(BaseModel):
    updates: dict[str, Any]
    merge: bool = True


# ═══════════════════════════════════════════════════════════════
#           Helpers
# ═══════════════════════════════════════════════════════════════

def _get_cluster_files(state: WebUIState):
    cf = getattr(state, "cluster_files", None)
    if cf is not None:
        return cf
    cf = getattr(state.config, "cluster_files", None)
    if cf is not None:
        return cf
    return None


def _check_key_perm(state: WebUIState, user, key_path: str) -> None:
    rules = state.config.get("webui.editor.config.key_permissions") or []
    user_roles = set(getattr(user, "roles", []) or [])

    for rule in rules:
        pat = rule.get("pattern")
        if not pat:
            continue
        try:
            if not re.match(pat, key_path):
                continue
        except re.error:
            continue
        allowed_roles = set(rule.get("roles") or [])
        if allowed_roles & user_roles:
            return
        raise HTTPException(
            403,
            f"Key '{key_path}' is restricted to roles: "
            f"{', '.join(sorted(allowed_roles))}",
        )

    if "admin" in user_roles:
        return
    raise HTTPException(403, f"Key '{key_path}' is admin-only")


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (data or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, str):
            out[key] = v
    return out


def _set_path(doc: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _delete_path(doc: dict, path: str) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]


def _apply_lang_updates(target_file: Path,
                        updates: dict[str, Optional[str]]) -> None:
    try:
        from ruamel.yaml import YAML
        y = YAML()
        y.preserve_quotes = True
        y.indent(mapping=2, sequence=4, offset=2)
        doc = {}
        if target_file.exists():
            with open(target_file, "r", encoding="utf-8") as f:
                doc = y.load(f) or {}
    except ImportError:
        import yaml as _yaml
        y = None
        doc = {}
        if target_file.exists():
            with open(target_file, "r", encoding="utf-8") as f:
                doc = _yaml.safe_load(f) or {}

    for path, value in updates.items():
        if value is None:
            _delete_path(doc, path)
        else:
            _set_path(doc, path, value)

    target_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_file.with_suffix(target_file.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        if y is not None:
            y.dump(doc, f)
        else:
            import yaml as _yaml
            _yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    tmp.replace(target_file)


# ═══════════════════════════════════════════════════════════════
#           Router
# ═══════════════════════════════════════════════════════════════

def build_router(state: WebUIState, deps: Dependencies, templates) -> APIRouter:
    router = APIRouter()

    paths = getattr(state.config, "paths", None)
    if paths is None:
        from lib.paths import Paths
        paths = Paths.from_config(state.config, state.root_dir / "config.yml")

    editor = FileEditor(paths)
    registry = ConfigRegistry(state.config, paths)
    locks = LockStore(state.config)
    history = EditorHistory(state.config)
    cluster_files = _get_cluster_files(state)
    cluster_enabled = cluster_files is not None

    # ═══════════════════════════════════════════════════════════
    #   HTML pages
    # ═══════════════════════════════════════════════════════════

    @router.get("/editor", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_VIEW))])
    def editor_root(request: Request):
        user = deps.current_user(request)
        if user.has_perm(PERM_EDITOR_CONFIG):
            return RedirectResponse("/editor/config", status_code=303)
        if user.has_perm(PERM_EDITOR_LANGS):
            return RedirectResponse("/editor/langs", status_code=303)
        if user.has_perm(PERM_EDITOR_COMMANDS):
            return RedirectResponse("/editor/files/commands", status_code=303)
        if user.has_perm(PERM_EDITOR_PLUGINS):
            return RedirectResponse("/editor/files/plugins", status_code=303)
        if user.has_perm(PERM_EDITOR_TEMPLATES):
            return RedirectResponse("/editor/files/templates", status_code=303)
        if user.has_perm(PERM_EDITOR_STATIC):
            return RedirectResponse("/editor/files/static", status_code=303)
        return RedirectResponse("/", status_code=303)

    @router.get("/editor/config", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def editor_config(request: Request):
        return templates.TemplateResponse(
            request=request, name="editor_config.html",
            context={"cluster_enabled": cluster_enabled},
        )

    @router.get("/editor/files/{category}", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_VIEW))])
    def editor_files_tree(request: Request, category: str):
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)
        return templates.TemplateResponse(
            request=request, name="editor_files.html",
            context={"category": category, "cluster_enabled": cluster_enabled},
        )

    @router.get("/editor/files/{category}/{file_path:path}",
                response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_VIEW))])
    def editor_file(request: Request, category: str, file_path: str):
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)
        return templates.TemplateResponse(
            request=request, name="editor_file.html",
            context={
                "category": category,
                "file_path": file_path,
                "cluster_enabled": cluster_enabled,
            },
        )

    @router.get("/editor/langs", response_class=HTMLResponse,
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_LANGS))])
    def editor_langs(request: Request):
        return templates.TemplateResponse(
            request=request, name="editor_langs.html",
            context={"cluster_enabled": cluster_enabled},
        )

    # ═══════════════════════════════════════════════════════════
    #   Config registry API
    # ═══════════════════════════════════════════════════════════

    # ─── 1) Tree ───

    @router.get("/api/editor/config/tree",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_tree():
        sections = registry.list_sections()
        leaf_counts = {s: len(registry.list_leaves_of(s)) for s in sections}

        sub_counts: dict[str, int] = {s: 0 for s in sections}
        for s in sections:
            if not s:
                continue
            parent = s.rsplit(".", 1)[0] if "." in s else ""
            sub_counts[parent] = sub_counts.get(parent, 0) + 1

        return [
            {
                "path": s,
                "name": s.rsplit(".", 1)[-1] if s else "(root)",
                "leaves": leaf_counts.get(s, 0),
                "subsections": sub_counts.get(s, 0),
            }
            for s in sections
        ]

    # ─── 2) Export / import ───

    @router.get("/api/editor/config/export",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_export():
        return JSONResponse(state.config.all())

    @router.post("/api/editor/config/import",
                 dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_import(req: ConfigImportReq,
                          user=Depends(deps.current_user)):
        applied: dict[str, str] = {}
        for path, value in req.updates.items():
            try:
                _check_key_perm(state, user, path)
                registry.set(path, value)
                applied[path] = "ok"
            except HTTPException as e:
                applied[path] = f"denied: {e.detail}"
            except ConfigRegistryError as e:
                applied[path] = f"error: {e}"
        return {"applied": applied}

    # ─── 3) Sections ───

    @router.get("/api/editor/config/section",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_section(path: str = ""):
        try:
            entries = registry.list_leaves_of(path)
        except Exception as e:
            raise HTTPException(400, str(e))
        return {
            "path": path,
            "entries": [
                {
                    "path": e.path,
                    "name": e.path.rsplit(".", 1)[-1],
                    "value": e.value,
                    "type": e.type,
                    "source": e.source,
                }
                for e in entries
            ],
        }

    @router.post("/api/editor/config/section",
                 dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_create_section(req: SectionCreateReq,
                                  user=Depends(deps.current_user)):
        _check_key_perm(state, user, req.path)
        try:
            registry.create_section(req.path)
        except ConfigRegistryError as e:
            raise HTTPException(409, str(e))

        # notify cluster
        publish_change({
            "type": "config.section.created",
            "path": req.path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })
        return {"created": req.path}

    @router.delete("/api/editor/config/section",
                   dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_delete_section(path: str,
                                  user=Depends(deps.current_user)):
        _check_key_perm(state, user, path)
        try:
            registry.delete_section(path)
        except ConfigRegistryError as e:
            raise HTTPException(409, str(e))

        # notify cluster
        publish_change({
            "type": "config.section.deleted",
            "path": path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })
        return {"deleted": path}

    # ─── 4) Values ───

    @router.post("/api/editor/config/value",
                 dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_create_value(req: ValueCreateReq,
                                user=Depends(deps.current_user)):
        _check_key_perm(state, user, req.path)
        try:
            entry = registry.create_value(req.path, req.value)
        except ConfigRegistryError as e:
            raise HTTPException(409, str(e))

        # notify cluster
        publish_change({
            "type": "config.value.created",
            "path": entry.path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })
        return {"path": entry.path, "value": entry.value, "type": entry.type}

    # ─── 5) Rename ───

    @router.post("/api/editor/config/rename",
                 dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_rename(req: RenameReq,
                          user=Depends(deps.current_user)):
        _check_key_perm(state, user, req.old_path)
        _check_key_perm(state, user, req.new_path)
        try:
            registry.rename(req.old_path, req.new_path)
        except ConfigRegistryError as e:
            raise HTTPException(409, str(e))

        # notify cluster
        publish_change({
            "type": "config.renamed",
            "old_path": req.old_path,
            "new_path": req.new_path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })
        return {"old": req.old_path, "new": req.new_path}

    # ─── 6) Greedy per-key routes (MUST BE LAST) ───

    @router.get("/api/editor/config/{key_path:path}",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_get(key_path: str):
        e = registry.get(key_path)
        if e is None:
            raise HTTPException(404, f"Key '{key_path}' not found")
        return {
            "path": e.path,
            "value": e.value,
            "type": e.type,
            "source": e.source,
        }

    @router.put("/api/editor/config/{key_path:path}",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_set(key_path: str, req: ConfigSetReq,
                       user=Depends(deps.current_user)):
        _check_key_perm(state, user, key_path)

        resource = f"config:{key_path}"
        lock = locks.get(resource)
        if lock and lock.owner != user.username:
            raise HTTPException(
                423, f"Locked by {lock.owner} until {lock.expires_at}"
            )

        before = registry.get(key_path)
        before_value = before.value if before else None

        try:
            entry = registry.set(key_path, req.value,
                                 expected_value=req.expected_value)
        except ConfigRegistryError as e:
            raise HTTPException(409, str(e))

        try:
            history.record(
                user=user.username,
                category="config",
                target=key_path,
                action="set",
                before=json.dumps(before_value, ensure_ascii=False, default=str),
                after=json.dumps(entry.value, ensure_ascii=False, default=str),
                source=entry.source,
            )
        except Exception:
            pass

        # ─── cluster sync via DB
        if cluster_enabled and entry.source:
            try:
                cluster_files.write(
                    category="config",
                    rel_path=entry.source,
                    content=Path(paths.base / entry.source)
                            .read_text(encoding="utf-8"),
                    author=user.username,
                )
            except Exception:
                pass

        # ─── cluster live notify (WS)
        publish_change({
            "type": "config.changed",
            "path": key_path,
            "value": entry.value,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {
            "path": entry.path,
            "value": entry.value,
            "type": entry.type,
            "source": entry.source,
        }

    @router.delete("/api/editor/config/{key_path:path}",
                   dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_config_delete(key_path: str,
                          user=Depends(deps.current_user)):
        _check_key_perm(state, user, key_path)

        resource = f"config:{key_path}"
        lock = locks.get(resource)
        if lock and lock.owner != user.username:
            raise HTTPException(423, f"Locked by {lock.owner}")

        before = registry.get(key_path)
        before_value = before.value if before else None

        try:
            registry.delete(key_path)
        except ConfigRegistryError as e:
            raise HTTPException(404, str(e))

        try:
            history.record(
                user=user.username,
                category="config",
                target=key_path,
                action="delete",
                before=json.dumps(before_value, ensure_ascii=False, default=str),
                after=None,
                source=before.source if before else None,
            )
        except Exception:
            pass

        if cluster_enabled and before and before.source:
            try:
                cluster_files.write(
                    category="config",
                    rel_path=before.source,
                    content=Path(paths.base / before.source)
                            .read_text(encoding="utf-8"),
                    author=user.username,
                )
            except Exception:
                pass

        # notify cluster
        publish_change({
            "type": "config.deleted",
            "path": key_path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {"deleted": key_path}

    # ═══════════════════════════════════════════════════════════
    #   File editor API
    # ═══════════════════════════════════════════════════════════

    @router.get("/api/editor/tree/{category}")
    def api_tree(category: str, path: str = "",
                 request: Request = None):  # noqa: B008
        if request is None:
            raise HTTPException(500, "Internal error")
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)
        try:
            return editor.list_tree(category, path)
        except EditorError as e:
            raise HTTPException(400, str(e))

    @router.get("/api/editor/file/{category}")
    def api_file_read(category: str, path: str, request: Request):
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)
        try:
            info, content = editor.read(category, path)
        except PermissionDenied as e:
            raise HTTPException(403, str(e))
        except EditorError as e:
            raise HTTPException(400, str(e))
        return {
            "path": info.path,
            "checksum": info.checksum,
            "size": info.size,
            "mtime": info.mtime,
            "content": content,
        }

    @router.put("/api/editor/file/{category}")
    def api_file_write(category: str, req: FileWriteReq,
                       request: Request):
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)

        if (category == "plugins"
                and req.path.endswith(PLUGIN_MANIFEST_SUFFIX)
                and not user.has_perm(PERM_EDITOR_PLUGINS_ADMIN)):
            raise HTTPException(403, "Editing plugin.json requires plugin admin")

        resource = f"file:{category}:{req.path}"
        lock = locks.get(resource)
        if lock and lock.owner != user.username:
            raise HTTPException(423, f"Locked by {lock.owner}")

        before_content: Optional[str] = None
        try:
            _, before_content = editor.read(category, req.path)
        except Exception:
            before_content = None

        try:
            if cluster_enabled:
                cluster_files.write(
                    category=category,
                    rel_path=req.path,
                    content=req.content,
                    author=user.username,
                )
                info = editor.info(category, req.path)
            else:
                info = editor.write(
                    category, req.path, req.content,
                    expected_checksum=req.expected_checksum,
                    create=req.create,
                )
        except PermissionDenied as e:
            raise HTTPException(403, str(e))
        except ConflictError as e:
            raise HTTPException(409, str(e))
        except EditorError as e:
            raise HTTPException(400, str(e))

        try:
            history.record(
                user=user.username,
                category="file",
                target=f"{category}:{req.path}",
                action="write",
                before=before_content,
                after=req.content,
                source=f"{category}:{req.path}",
            )
        except Exception:
            pass

        # notify cluster
        publish_change({
            "type": "file.changed",
            "category": category,
            "path": req.path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {
            "path": info.path,
            "checksum": info.checksum,
            "size": info.size,
            "mtime": info.mtime,
            "cluster": cluster_enabled,
        }

    @router.delete("/api/editor/file/{category}")
    def api_file_delete(category: str, req: FileDeleteReq,
                        request: Request):
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)

        if (category == "plugins"
                and req.path.endswith(PLUGIN_MANIFEST_SUFFIX)
                and not user.has_perm(PERM_EDITOR_PLUGINS_ADMIN)):
            raise HTTPException(403)

        before_content: Optional[str] = None
        try:
            _, before_content = editor.read(category, req.path)
        except Exception:
            before_content = None

        try:
            if cluster_enabled:
                cluster_files.delete(
                    category=category,
                    rel_path=req.path,
                    author=user.username,
                )
                try:
                    editor.delete(category, req.path)
                except Exception:
                    pass
            else:
                editor.delete(category, req.path)
        except EditorError as e:
            raise HTTPException(400, str(e))

        try:
            history.record(
                user=user.username,
                category="file",
                target=f"{category}:{req.path}",
                action="delete",
                before=before_content,
                after=None,
                source=f"{category}:{req.path}",
            )
        except Exception:
            pass

        # notify cluster
        publish_change({
            "type": "file.deleted",
            "category": category,
            "path": req.path,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {"deleted": req.path, "cluster": cluster_enabled}

    @router.post("/api/editor/mkdir/{category}")
    def api_mkdir(category: str, req: MkdirReq, request: Request):
        perm = CATEGORY_PERM.get(category)
        if not perm:
            raise HTTPException(404)
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)
        try:
            editor.mkdir(category, req.path)
        except EditorError as e:
            raise HTTPException(400, str(e))
        return {"created": req.path}

    @router.post("/api/editor/validate")
    def api_validate(req: ValidateReq, request: Request):
        perm = CATEGORY_PERM.get(req.category) or PERM_EDITOR_VIEW
        user = deps.current_user(request)
        if not user.has_perm(perm):
            raise HTTPException(403)

        errors: list[dict] = []
        ext = ""
        if req.path:
            ext = req.path.rsplit(".", 1)[-1].lower()

        if ext in ("yml", "yaml"):
            try:
                import yaml
                yaml.safe_load(req.content)
            except Exception as e:
                line = getattr(e, "problem_mark", None)
                errors.append({
                    "line": (line.line + 1) if line else None,
                    "column": (line.column + 1) if line else None,
                    "message": str(e),
                    "severity": "error",
                })
        elif ext == "py":
            import ast
            try:
                ast.parse(req.content)
            except SyntaxError as e:
                errors.append({
                    "line": e.lineno,
                    "column": e.offset,
                    "message": e.msg,
                    "severity": "error",
                })
        elif ext == "json":
            try:
                json.loads(req.content)
            except Exception as e:
                errors.append({
                    "line": getattr(e, "lineno", None),
                    "column": getattr(e, "colno", None),
                    "message": str(e),
                    "severity": "error",
                })

        return {"errors": errors}

    # ═══════════════════════════════════════════════════════════
    #   Locks API
    # ═══════════════════════════════════════════════════════════

    @router.get("/api/editor/lock")
    def api_lock_list():
        return [
            {
                "resource": l.resource,
                "owner": l.owner,
                "expires_at": l.expires_at.isoformat() if l.expires_at else None,
            }
            for l in locks.list()
        ]

    @router.post("/api/editor/lock")
    def api_lock_acquire(req: LockReq, request: Request,
                         user=Depends(deps.current_user)):
        if not user.has_perm(PERM_EDITOR_VIEW):
            raise HTTPException(403)
        try:
            info = locks.acquire(
                req.resource,
                owner=user.username,
                ttl_seconds=req.ttl,
                client_ip=request.client.host if request.client else None,
            )
        except LockError as e:
            raise HTTPException(423, str(e))
        return {
            "resource": info.resource,
            "owner": info.owner,
            "token": info.token,
            "expires_at": info.expires_at.isoformat() if info.expires_at else None,
        }

    @router.post("/api/editor/lock/refresh")
    def api_lock_refresh(req: LockRefreshReq,
                         user=Depends(deps.current_user)):
        try:
            info = locks.refresh(
                req.resource, user.username, req.token, ttl_seconds=req.ttl,
            )
        except LockError as e:
            raise HTTPException(423, str(e))
        return {
            "resource": info.resource,
            "token": info.token,
            "expires_at": info.expires_at.isoformat() if info.expires_at else None,
        }

    @router.post("/api/editor/lock/release")
    def api_lock_release(req: LockReleaseReq,
                         user=Depends(deps.current_user)):
        try:
            ok = locks.release(req.resource, user.username, req.token)
        except LockError as e:
            raise HTTPException(423, str(e))
        return {"released": ok}

    # ═══════════════════════════════════════════════════════════
    #   History API
    # ═══════════════════════════════════════════════════════════

    @router.get("/api/editor/history",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_VIEW))])
    def api_history(category: Optional[str] = None,
                    target: Optional[str] = None,
                    limit: int = 100):
        entries = history.list(category=category, target=target, limit=limit)
        return [
            {
                "id": e.id,
                "ts": e.ts.isoformat() if e.ts else None,
                "user": e.user,
                "category": e.category,
                "target": e.target,
                "action": e.action,
                "source": e.source,
            }
            for e in entries
        ]

    @router.get("/api/editor/history/{entry_id}",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_VIEW))])
    def api_history_get(entry_id: int):
        e = history.get(entry_id)
        if not e:
            raise HTTPException(404)
        return {
            "id": e.id,
            "ts": e.ts.isoformat() if e.ts else None,
            "user": e.user,
            "category": e.category,
            "target": e.target,
            "action": e.action,
            "before": e.before,
            "after": e.after,
            "source": e.source,
        }

    @router.get("/api/editor/history/{entry_id}/diff",
                dependencies=[Depends(deps.require_perm(PERM_EDITOR_VIEW))])
    def api_history_diff(entry_id: int):
        e = history.get(entry_id)
        if not e:
            raise HTTPException(404)
        before = (e.before or "").splitlines(keepends=True)
        after = (e.after or "").splitlines(keepends=True)
        diff = difflib.unified_diff(
            before, after,
            fromfile=f"{e.target} (before)",
            tofile=f"{e.target} (after)",
        )
        return {"diff": "".join(diff)}

    @router.post("/api/editor/history/{entry_id}/rollback",
                 dependencies=[Depends(deps.require_perm(PERM_EDITOR_CONFIG))])
    def api_rollback(entry_id: int,
                     user=Depends(deps.current_user)):
        e = history.get(entry_id)
        if not e:
            raise HTTPException(404)
        if e.before is None:
            raise HTTPException(400, "No previous content to roll back to")

        if e.category == "file":
            if ":" not in e.target:
                raise HTTPException(400, "Malformed target")
            cat, path = e.target.split(":", 1)

            if cluster_enabled:
                cluster_files.write(
                    category=cat, rel_path=path,
                    content=e.before, author=user.username,
                )
            else:
                editor.write(cat, path, e.before, create=True)

        elif e.category == "config":
            target_key = e.target
            try:
                before_value = json.loads(e.before) if e.before else None
            except Exception:
                before_value = e.before
            try:
                registry.set(target_key, before_value)
            except ConfigRegistryError as exc:
                raise HTTPException(400, str(exc))

        history.record(
            user=user.username,
            category=e.category,
            target=e.target,
            action="rollback",
            before=e.after,
            after=e.before,
            source=e.source,
        )

        # notify cluster
        publish_change({
            "type": "history.rollback",
            "entry_id": entry_id,
            "target": e.target,
            "category": e.category,
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {"rolled_back": entry_id}

    # ═══════════════════════════════════════════════════════════
    #   Translations API
    # ═══════════════════════════════════════════════════════════

    @router.get("/api/editor/langs")
    def api_langs_list():
        i18n = get_i18n()
        return {
            "available": i18n.available_locales(),
            "default": i18n.default_locale,
            "fallback": i18n.fallback_locale,
        }

    @router.get("/api/editor/langs/{locale}")
    def api_langs_dict(locale: str):
        i18n = get_i18n()
        if locale not in i18n.available_locales():
            raise HTTPException(404)
        return _flatten(i18n._translations.get(locale, {}))

    @router.get("/api/editor/langs/{locale}/tree")
    def api_langs_tree(locale: str):
        i18n = get_i18n()
        if locale not in i18n.available_locales():
            raise HTTPException(404)

        fb = i18n._translations.get(i18n.fallback_locale, {}) or {}
        cur = i18n._translations.get(locale, {}) or {}

        fb_keys = set(_flatten(fb).keys())
        cur_keys = set(_flatten(cur).keys())
        all_keys = fb_keys | cur_keys

        sections: set[str] = {""}
        for key in all_keys:
            parts = key.split(".")
            for i in range(1, len(parts)):
                sections.add(".".join(parts[:i]))

        leaf_counts: dict[str, int] = {s: 0 for s in sections}
        sub_counts: dict[str, int] = {s: 0 for s in sections}
        for key in all_keys:
            parent = key.rsplit(".", 1)[0] if "." in key else ""
            leaf_counts[parent] = leaf_counts.get(parent, 0) + 1
        for s in sections:
            if not s:
                continue
            parent = s.rsplit(".", 1)[0] if "." in s else ""
            sub_counts[parent] = sub_counts.get(parent, 0) + 1

        return [
            {
                "path": s,
                "name": s.rsplit(".", 1)[-1] if s else "(root)",
                "leaves": leaf_counts.get(s, 0),
                "subsections": sub_counts.get(s, 0),
            }
            for s in sorted(sections)
        ]

    @router.get("/api/editor/langs/{locale}/section")
    def api_langs_section(locale: str, path: str = ""):
        i18n = get_i18n()
        if locale not in i18n.available_locales():
            raise HTTPException(404)

        fb_locale = i18n.fallback_locale
        fb_flat = _flatten(i18n._translations.get(fb_locale, {}) or {})
        cur_flat = _flatten(i18n._translations.get(locale, {}) or {})

        prefix = path + "." if path else ""
        keys_in_section: set[str] = set()
        for k in fb_flat:
            if k.startswith(prefix) and "." not in k[len(prefix):]:
                keys_in_section.add(k)
        for k in cur_flat:
            if k.startswith(prefix) and "." not in k[len(prefix):]:
                keys_in_section.add(k)

        out = []
        for key in sorted(keys_in_section):
            cur_val = cur_flat.get(key)
            fb_val = fb_flat.get(key)
            layer = None
            try:
                layer = i18n.key_source(locale, key)
                if layer is None:
                    layer = i18n.key_source(fb_locale, key)
            except Exception:
                layer = None

            if cur_val is None and fb_val is not None:
                status = "missing"
            elif cur_val is not None and fb_val is not None and cur_val == fb_val:
                status = "same-as-fallback"
            elif cur_val is not None and fb_val is None:
                status = "extra"
            else:
                status = "ok"

            out.append({
                "key": key,
                "name": key.rsplit(".", 1)[-1],
                "value": cur_val,
                "fallback": fb_val,
                "layer": layer,
                "status": status,
            })

        return {"path": path, "entries": out}

    @router.put("/api/editor/langs/{locale}")
    def api_langs_update(locale: str, req: LangSetReq,
                         request: Request,
                         user=Depends(deps.current_user)):
        if not user.has_perm(PERM_EDITOR_LANGS):
            raise HTTPException(403)

        target_file = paths.langs_dir / f"{locale}.yml"
        before_content: Optional[str] = None
        try:
            if target_file.exists():
                before_content = target_file.read_text(encoding="utf-8")
        except Exception:
            before_content = None

        _apply_lang_updates(target_file, req.updates)
        get_i18n().reload()

        try:
            history.record(
                user=user.username,
                category="file",
                target=f"langs:{locale}.yml",
                action="langs-update",
                before=before_content,
                after=target_file.read_text(encoding="utf-8")
                       if target_file.exists() else None,
                source=f"langs:{locale}.yml",
            )
        except Exception:
            pass

        if cluster_enabled:
            try:
                cluster_files.write(
                    category="langs",
                    rel_path=f"{locale}.yml",
                    content=target_file.read_text(encoding="utf-8"),
                    author=user.username,
                )
            except Exception:
                pass

        # notify cluster
        publish_change({
            "type": "langs.changed",
            "locale": locale,
            "keys": list(req.updates.keys()),
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {"updated": list(req.updates.keys()), "cluster": cluster_enabled}

    @router.post("/api/editor/langs/{locale}/sync")
    def api_langs_sync(locale: str, request: Request,
                       user=Depends(deps.current_user)):
        if not user.has_perm(PERM_EDITOR_LANGS):
            raise HTTPException(403)

        i18n = get_i18n()
        if locale not in i18n.available_locales():
            raise HTTPException(404)

        fb_locale = i18n.fallback_locale
        fb_dict = _flatten(i18n._translations.get(fb_locale, {}))
        cur_dict = _flatten(i18n._translations.get(locale, {}))

        missing = {k: v for k, v in fb_dict.items() if k not in cur_dict}
        if not missing:
            return {"synced": 0, "cluster": cluster_enabled}

        target_file = paths.langs_dir / f"{locale}.yml"
        before_content: Optional[str] = None
        try:
            if target_file.exists():
                before_content = target_file.read_text(encoding="utf-8")
        except Exception:
            before_content = None

        _apply_lang_updates(target_file, missing)
        get_i18n().reload()

        try:
            history.record(
                user=user.username,
                category="file",
                target=f"langs:{locale}.yml",
                action="langs-sync",
                before=before_content,
                after=target_file.read_text(encoding="utf-8")
                       if target_file.exists() else None,
                source=f"langs:{locale}.yml",
            )
        except Exception:
            pass

        if cluster_enabled:
            try:
                cluster_files.write(
                    category="langs",
                    rel_path=f"{locale}.yml",
                    content=target_file.read_text(encoding="utf-8"),
                    author=user.username,
                )
            except Exception:
                pass

        # notify cluster
        publish_change({
            "type": "langs.synced",
            "locale": locale,
            "count": len(missing),
            "author": user.username,
            "ts": datetime.now().isoformat(),
        })

        return {"synced": len(missing), "cluster": cluster_enabled}

    return router
