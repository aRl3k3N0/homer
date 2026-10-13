"""
Extension registry for menu items and additional routes.

Any component (plugin, project) can register:

    - menu items:  sidebar/navbar entries with URL + required permission
    - routes:      additional APIRouters mounted under a namespace

The registry is built from:
    1. Plugin __init__.py that calls `webui_extend(registry)`.
    2. Project's own `webui_extensions.py` (optional file next to config.yml).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter


@dataclass
class TemplateDir:
    path: Path
    priority: int = 100

@dataclass
class MenuItem:
    label_key: str               # i18n key for the label
    url: str
    icon: str = ""
    perm: Optional[str] = None   # required permission
    order: int = 100
    group: str = "main"          # navbar | admin | editor | main
    new_tab: bool = False

    def to_dict(self):
        return {
            "label_key": self.label_key,
            "url": self.url,
            "icon": self.icon,
            "perm": self.perm,
            "order": self.order,
            "group": self.group,
            "new_tab": self.new_tab,
        }


@dataclass
class RouteEntry:
    prefix: str
    router: APIRouter
    perm: Optional[str] = None
    source: str = ""


class ExtensionRegistry:
    def __init__(self):
        self._menu: list[MenuItem] = []
        self._routes: list[RouteEntry] = []

    # ─────────── Registration ───────────

    def menu(self, item: MenuItem):
        self._menu.append(item)

    def route(self, prefix: str, router: APIRouter,
              perm: Optional[str] = None, source: str = ""):
        self._routes.append(RouteEntry(prefix, router, perm, source))

    # ─────────── Access ───────────

    def menu_items(self, group: Optional[str] = None) -> list[MenuItem]:
        items = self._menu
        if group:
            items = [i for i in items if i.group == group]
        return sorted(items, key=lambda i: (i.order, i.label_key))

    def routes(self) -> list[RouteEntry]:
        return list(self._routes)

    def template_dir(self, path: Path, priority: int = 100):
        self._templates.append(TemplateDir(Path(path), priority))


def load_extensions(registry: ExtensionRegistry,
                    root_dir: Path,
                    config,
                    plugin_mgr) -> None:
    """
    Load menu and route extensions from:
        - every plugin's `webui_extend(registry)` hook
        - the project's `webui_extensions.py` file (if present)
    """
    # 1) Plugins
    for p in plugin_mgr.list():
        module = p.module if hasattr(p, "module") else None
        if module is None:
            module = _try_load_module(p.path / "__init__.py")
        if module is None:
            continue
        fn = getattr(module, "webui_extend", None)
        if callable(fn):
            try:
                fn(registry)
            except Exception:
                pass

    # 2) Project file
    project_file = root_dir / "webui_extensions.py"
    if project_file.exists():
        module = _try_load_module(project_file)
        if module:
            fn = getattr(module, "webui_extend", None)
            if callable(fn):
                try:
                    fn(registry)
                except Exception:
                    pass


def _try_load_module(path: Path):
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"homer_ext_{path.stem}", path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None
