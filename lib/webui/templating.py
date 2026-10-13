"""
Jinja environment factory for the Web UI.

Combines:
    - core templates:    lib/webui/templates
    - project templates: <project>/templates
    - plugin templates:  <project>/plugins/<name>/templates

Registers i18n globals and filters, and a per-request `user` /
`locale` accessor for RequestAwareJinja2Templates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

from lib.i18n import get_i18n


CORE_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ═══════════════════════════════════════════════════════════════
#           Request-aware Jinja2Templates
# ═══════════════════════════════════════════════════════════════

class RequestAwareJinja2Templates(Jinja2Templates):
    """
    Jinja2Templates that inject per-request values into every
    rendering context:
        - user    (from request.state.user)
        - locale  (from i18n.get_i18n().locale)
    """

    def TemplateResponse(self, *args, **kwargs):
        request = kwargs.get("request")
        if request is None and args and isinstance(args[0], Request):
            request = args[0]

        if request is not None:
            ctx = kwargs.get("context") or {}

            ctx.setdefault("user", getattr(request.state, "user", None))

            from lib.i18n import get_i18n
            i18n = get_i18n()
            ctx.setdefault("locale", i18n.locale)

            kwargs["context"] = ctx

        return super().TemplateResponse(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════
#           Template environment
# ═══════════════════════════════════════════════════════════════

def build_templates(project_templates_dir: Path | None = None,
                    plugin_dirs: list[Path] | None = None
                    ) -> RequestAwareJinja2Templates:
    """
    Create and return Jinja2Templates with:
        - loader: core + project + plugins
        - i18n globals and filters
        - per-request `user` and `locale`
    """
    search_dirs: list[Path] = [CORE_TEMPLATES_DIR]

    if project_templates_dir and project_templates_dir.exists():
        search_dirs.append(project_templates_dir)

    for d in (plugin_dirs or []):
        if d and d.exists():
            search_dirs.append(d)

    # ─── Create the environment ───
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader(str(d)) for d in search_dirs]),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # ─── i18n ───
    i18n = get_i18n()
    env.globals["_"] = i18n.jinja_global()
    env.globals["tn"] = i18n.jinja_plural_global()
    env.globals["available_locales"] = lambda: i18n.available_locales()
    env.globals["can"] = _can

    for name, fn in i18n.jinja_filters().items():
        env.filters[name] = fn

    # ─── UI-specific ───
    env.filters["status_color"] = _status_color

    # ─── Menu extension global ───
    env.globals["extension_menu"] = _extension_menu

    return RequestAwareJinja2Templates(env=env)


# ═══════════════════════════════════════════════════════════════
#           Helpers
# ═══════════════════════════════════════════════════════════════

def _status_color(status: str) -> str:
    return {
        "pending": "warning",
        "running": "info",
        "done": "success",
        "failed": "danger",
        "canceled": "secondary",
        "timeout": "dark",
    }.get(status, "light")


def _can(user: Any, perm: str) -> bool:
    """Safe permission check for Jinja: never raises."""
    if user is None:
        return False
    if not hasattr(user, "has_perm"):
        return False
    try:
        return bool(user.has_perm(perm))
    except Exception:
        return False


def _extension_menu(group: str = "main") -> list[dict]:
    """
    Return menu items from the extension registry.
    The registry is attached to this function by app.py at startup.
    """
    registry = getattr(_extension_menu, "_registry", None)
    if registry is None:
        return []
    try:
        return [i.to_dict() for i in registry.menu_items(group)]
    except Exception:
        return []
