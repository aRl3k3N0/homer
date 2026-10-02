"""
Plugin manager with optional registry cache integration.

On every startup the manager tries to load cached plugin metadata
(var/cache/registry.json). If the cache is fresh, `discover()` reuses
it. Otherwise it falls back to a full filesystem scan and updates
the cache.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Optional

from .plugin import PluginInfo, PluginState
from ..registry_cache import RegistryCache

_log = logging.getLogger("homer.plugins")


class PluginManager:
    def __init__(self, *, registry_cache: Optional[RegistryCache] = None):
        self._plugins: dict[str, PluginInfo] = {}
        self._root: Optional[Path] = None
        self._config = None
        self._initialized: set[str] = set()
        self._registry_cache = registry_cache

    # ─────────── Discovery ───────────

    def discover(self, plugins_dir: Path, config=None, *, use_cache: bool = True) -> list[PluginInfo]:
        """
        Scan plugins directory.

        If use_cache=True and a fresh RegistryCache is available,
        plugin metadata is loaded from the cache instead of walking
        the filesystem. On miss, we rescan and rewrite the cache.
        """
        self._root = Path(plugins_dir)
        self._config = config
        self._plugins.clear()

        if not self._root.exists():
            return []

        cached = None
        if use_cache and self._registry_cache is not None:
            cached = self._registry_cache.load()
            if cached and not self._registry_cache.is_fresh(cached):
                _log.info("registry cache is stale, rescanning plugins")
                cached = None

        if cached:
            cached_plugins = cached.get("plugins") or {}
            if cached_plugins:
                _log.info("registry cache hit: %d plugins", len(cached_plugins))
                for name, meta in cached_plugins.items():
                    plugin_path = self._root.parent / meta["path"]
                    if not plugin_path.exists():
                        _log.warning("cached plugin '%s' no longer exists", name)
                        continue
                    try:
                        info = PluginInfo.from_dir(plugin_path)
                        self._plugins[info.name] = info
                    except Exception as e:
                        _log.warning("cached plugin '%s' unreadable: %s", name, e)
                return list(self._plugins.values())

        # Full scan
        _log.info("registry cache miss: scanning %s", self._root)
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith((".", "_")):
                continue
            manifest = entry / "plugin.json"
            if not manifest.exists():
                continue
            try:
                info = PluginInfo.from_dir(entry)
            except Exception as e:
                _log.warning("plugin '%s' skipped: %s", entry.name, e)
                continue
            self._plugins[info.name] = info

        return list(self._plugins.values())

    # ─────────── Snapshot update ───────────

    def update_registry_cache(self, *, commands: dict, langs_dirs: list[Path]) -> None:
        """
        Rebuild the cache after a full discovery. Called from homer once
        both commands and plugins are known.
        """
        if self._registry_cache is None:
            return
        try:
            snapshot = self._registry_cache.build_snapshot(
                commands=commands,
                plugins=list(self._plugins.values()),
                langs_dirs=langs_dirs,
            )
            self._registry_cache.save(snapshot)
            _log.info("registry cache updated: %d commands, %d plugins",
                      len(snapshot.get("commands") or {}),
                      len(snapshot.get("plugins") or {}))
        except Exception as e:
            _log.error("failed to update registry cache: %s", e, exc_info=True)

    # ─────────── Rest (unchanged) ───────────

    def load_all(self, context: dict | None = None, *, homer_version: Optional[str] = None,
                 validate: bool = True):
        enabled = self._enabled_names()
        for name, info in self._plugins.items():
            if name not in enabled:
                info.state = PluginState.DISABLED
                continue
            if name in self._initialized:
                continue
            self._load_one(info, context)

    def _load_one(self, info: PluginInfo, context: dict | None):
        try:
            module = self._import_plugin(info)
            info.state = PluginState.LOADED
            init = getattr(module, "plugin_init", None)
            if callable(init):
                try:
                    init(context or {})
                except Exception as e:
                    info.state = PluginState.ERROR
                    info.error = f"plugin_init: {e}"
                    _log.error("plugin '%s' init error: %s", info.name, e, exc_info=True)
                    return
            info.state = PluginState.ENABLED
            self._initialized.add(info.name)
            _log.info("plugin '%s' v%s loaded", info.name, info.version)
        except Exception as e:
            info.state = PluginState.ERROR
            info.error = str(e)
            _log.error("failed to load plugin '%s': %s", info.name, e, exc_info=True)

    def _import_plugin(self, info: PluginInfo):
        init_py = info.path / "__init__.py"
        module_name = f"homer_plugin_{info.name}"
        if not init_py.exists():
            spec = importlib.util.spec_from_loader(module_name, loader=None)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            return module
        spec = importlib.util.spec_from_file_location(module_name, init_py)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        pkg_path = str(info.path)
        if pkg_path not in sys.path:
            sys.path.insert(0, pkg_path)
        spec.loader.exec_module(module)
        return module

    def _enabled_names(self) -> set[str]:
        if self._config is None:
            return set(self._plugins.keys())
        enabled = self._config.get("plugins.enabled")
        if enabled is None or enabled == ["*"] or enabled == "*":
            return set(self._plugins.keys())
        disabled = set(self._config.get("plugins.disabled", []) or [])
        return set(enabled) - disabled

    def list(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    def get(self, name: str) -> Optional[PluginInfo]:
        return self._plugins.get(name)

    def paths_for(self, kind: str) -> list[Path]:
        result = []
        for info in self._plugins.values():
            if info.state not in (PluginState.LOADED, PluginState.ENABLED,
                                  PluginState.MIGRATED):
                continue
            p = getattr(info, f"{kind}_dir", None)
            if p:
                result.append(p)
        return result


_manager: Optional[PluginManager] = None


def get_manager() -> PluginManager:
    """

    :rtype: object
    """
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager


# ─────────── SQL-утилиты ───────────


def _split_sql(text: str, driver: str) -> list[str]:
    """Compatibility wrapper for the shared SQL migration parser."""
    from lib.migrations.sql import split_sql

    return split_sql(text, driver)

