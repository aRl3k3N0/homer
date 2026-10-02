"""
Command loader with optional lazy import.

Two modes:
    eager  -- import every module immediately (original behaviour)
    lazy   -- read metadata from cache, import only when executing

Lazy mode is triggered by `commands` dict containing entries with
'lazy': True and a 'path' key. In that case `get_command(name)` loads
the module on demand, while `load_commands()` returns metadata as-is.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("homer.command_loader")


class CommandLoader:
    def __init__(self, commands_dir: Path, *, root_dir: Optional[Path] = None):
        """
        commands_dir -- directory containing user commands.
        root_dir     -- project root (used to resolve plugin paths).
                        Defaults to commands_dir.parent.
        """
        self.commands_dir = Path(commands_dir)
        self.root_dir = Path(root_dir) if root_dir else self.commands_dir.parent
        self.plugin_dirs: list[tuple[str, Path]] = []
        self._loaded: dict[str, dict[str, Any]] = {}

    # ─────────── Plugin registration ───────────

    def add_plugin_commands(self, plugin_name: str, plugin_commands_dir: Path) -> None:
        """
        Register a plugin's commands directory. Commands will be exposed
        as '<plugin_name>:<local_name>'.
        """
        self.plugin_dirs.append((plugin_name, Path(plugin_commands_dir)))

    # ─────────── Public loading API ───────────

    def load_commands(self) -> dict[str, dict[str, Any]]:
        """
        Return all commands (user + plugin) as metadata dicts.
        In lazy mode each entry has 'lazy': True and 'path'; the module
        is not imported yet.
        """
        commands: dict[str, dict[str, Any]] = {}

        # User commands
        if self.commands_dir.exists():
            for py in self.commands_dir.rglob("*.py"):
                if py.name == "__init__.py":
                    continue
                name = self._get_command_name(py, self.commands_dir)
                if not name:
                    continue
                meta = self._metadata_only(py, name, source="user")
                if meta:
                    commands[name] = meta

        # Plugin commands
        for plugin_name, pdir in self.plugin_dirs:
            if not pdir.exists():
                continue
            for py in pdir.rglob("*.py"):
                if py.name == "__init__.py":
                    continue
                local = self._get_command_name(py, pdir)
                if not local:
                    continue
                full = f"{plugin_name}:{local}"
                meta = self._metadata_only(py, full, source=f"plugin:{plugin_name}")
                if meta:
                    commands[full] = meta

        self._loaded = commands
        return commands

    def get_command(self, name: str) -> Optional[dict[str, Any]]:
        """
        Load a single command module (import on demand in lazy mode).
        Returns metadata with 'execute' callable, or None.
        """
        if not self._loaded:
            self.load_commands()
        info = self._loaded.get(name)
        if not info:
            return None

        if info.get("lazy"):
            try:
                module = self._import_module(info["path"])
            except Exception as e:
                _log.error("Failed to import command '%s' from %s: %s",
                           name, info["path"], e, exc_info=True)
                return None
            info.update({
                "module": module,
                "execute": getattr(module, "execute", None),
                "lazy": False,
            })
            if info["execute"] is None:
                _log.warning("Command '%s' has no execute() function", name)
                return None
        return info

    def metadata(self) -> dict[str, dict[str, Any]]:
        """Return metadata for all commands (no imports)."""
        if not self._loaded:
            self.load_commands()
        return self._loaded

    # ─────────── Internals ───────────

    def _metadata_only(
        self,
        py_file: Path,
        name: str,
        *,
        source: str,
    ) -> Optional[dict[str, Any]]:
        """
        Build metadata without importing the module.

        We do a tiny AST-less scan: read first ~2 KB of the file and
        look for a top-level DESCRIPTION assignment. If not found,
        we leave description empty. Full description is only available
        after import, which we defer.
        """
        description = ""
        try:
            head = py_file.read_text(encoding="utf-8", errors="replace")[:4096]
            description = self._extract_description(head)
        except Exception:
            pass

        return {
            "path": py_file,
            "description": description,
            "source": source,
            "lazy": True,
            "module": None,
            "execute": None,
        }

    @staticmethod
    def _extract_description(source: str) -> str:
        """
        Extract DESCRIPTION = "..." from the file header, without exec.
        Falls back to the module docstring first line.
        """
        import re
        # DESCRIPTION = "..." or '...'
        m = re.search(
            r'^\s*DESCRIPTION\s*=\s*["\'](.+?)["\']',
            source,
            re.MULTILINE,
        )
        if m:
            return m.group(1).strip()
        # docstring: """First line"""
        m = re.search(r'^\s*(?:"""|\'\'\')\s*(.+?)\s*(?:"""|\'\'\')',
                      source, re.MULTILINE | re.DOTALL)
        if m:
            first = m.group(1).strip().splitlines()[0] if m.group(1).strip() else ""
            return first
        return ""

    def _import_module(self, path: Path):
        """
        Import a single Python file as a module.
        The module name is derived from the path to keep sys.modules
        deterministic.
        """
        rel = path.relative_to(self.root_dir) if path.is_absolute() else path
        name = "homer_cmd_" + str(rel).replace("/", "_").replace("\\", "_").replace(".py", "")
        spec = importlib.util.spec_from_file_location(name, path)
        if not spec or not spec.loader:
            raise ImportError(f"cannot load spec for {path}")
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _get_command_name(py_file: Path, base: Path) -> Optional[str]:
        rel = py_file.relative_to(base)
        parts = list(rel.parts)
        parts[-1] = parts[-1].replace(".py", "")
        if parts[-1] == "main":
            parts = parts[:-1]
            if not parts:
                return None
        return ":".join(parts)
