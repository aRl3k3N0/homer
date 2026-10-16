"""
Cache for command and plugin metadata.

Purpose
-------
Scanning `commands/` and `plugins/` on every CLI invocation is expensive:
walking the tree, importing modules to read DESCRIPTION, parsing
plugin.json. For 20+ commands this takes hundreds of milliseconds.

This cache stores metadata (path, description, source) in a single JSON
file, invalidated by mtime and size of the root directories and of each
individual file. Module code itself is NOT cached -- only metadata.
Actual imports happen lazily, at the moment of execution.

Layout
------
    var/cache/registry.json

Structure
---------
{
  "version": 1,
  "generated_at": "2026-10-02T12:00:00",
  "homer_version": "1.0.0",
  "commands_dir_mtime": 1759400000.123,
  "plugins_dir_mtime": 1759400000.456,
  "commands": {
    "hello": {
      "path": "commands/hello.py",
      "description": "Greeting command",
      "source": "user"
    },
    "notes:add": {
      "path": "plugins/notes/commands/add.py",
      "description": "Add a note",
      "source": "plugin:notes"
    }
  },
  "plugins": {
    "notes": {
      "path": "plugins/notes",
      "version": "1.2.0",
      "requires": [],
      "requires_homer": ">=1.0.0",
      "auto_migrate": true,
      "has_commands": true,
      "has_langs": true,
      "has_migrations": true,
      "has_templates": false,
      "has_static": true,
      "has_email": false,
      "has_lib": false
    }
  },
  "langs_dirs": ["langs", "plugins/notes/langs"],
  "files": {
    "commands/hello.py": {"mtime": 1759399999.123, "size": 512}
  }
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional
from homer import __version__

_log = logging.getLogger("homer.registry_cache")

CACHE_VERSION = 1

# ─────────────────────────────────────────────────────────────
#  JSON safety helpers
# ─────────────────────────────────────────────────────────────

def _json_safe(value: Any) -> Any:
    """
    Convert a value into something that json.dumps can handle.

    - Primitive types (str, int, float, bool, None) are returned as-is.
    - Path becomes str.
    - dict / list / tuple / set are processed recursively.
    - Everything else (functions, classes, modules, arbitrary objects)
      becomes its repr(), so nothing crashes the serializer.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return repr(value)


# ─────────────────────────────────────────────────────────────
#  Dataclasses for typed access
# ─────────────────────────────────────────────────────────────

@dataclass
class CachedCommand:
    path: str
    description: str = ""
    source: str = "user"


@dataclass
class CachedPlugin:
    path: str
    version: str = "0.0.0"
    requires: list[str] = None
    requires_homer: str = ">=1.0.0"
    auto_migrate: bool = True
    has_commands: bool = False
    has_langs: bool = False
    has_migrations: bool = False
    has_templates: bool = False
    has_static: bool = False
    has_email: bool = False
    has_lib: bool = False


# ─────────────────────────────────────────────────────────────
#  RegistryCache
# ─────────────────────────────────────────────────────────────

class RegistryCache:
    """
    Persistent metadata cache stored as a single JSON file.

    Use cases:
        1. Fast CLI startup: skip filesystem scan if nothing changed.
        2. Listing commands/plugins without importing modules.
        3. Detecting changes: any mismatch → cache miss → full rescan.

    Not a source of truth. If invalidation is uncertain, we rescan.
    """

    def __init__(
        self,
        root: Path,
        *,
        cache_path: Optional[Path] = None,
        commands_dir: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        enabled: bool = True,
    ):
        self.root = Path(root)
        self.enabled = enabled
        self.cache_path = (
            Path(cache_path) if cache_path else self.root / "var" / "cache" / "registry.json"
        )
        self.commands_dir = Path(commands_dir) if commands_dir else self.root / "commands"
        self.plugins_dir = Path(plugins_dir) if plugins_dir else self.root / "plugins"

    # ─────────── Load / Save ───────────

    def load(self) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("registry cache: failed to load %s: %s",
                         self.cache_path, e)
            return None
        if data.get("version") != CACHE_VERSION:
            _log.info("registry cache: version mismatch, ignoring (have=%s, want=%s)",
                      data.get("version"), CACHE_VERSION)
            return None
        return data

    def save(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return

        # Sanitize the whole payload — never trust the caller.
        data = _json_safe(data)
        data["version"] = CACHE_VERSION
        data["generated_at"] = datetime.now().isoformat()

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.cache_path)
        except Exception as e:
            _log.error("registry cache: failed to save %s: %s",
                       self.cache_path, e)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def clear(self) -> bool:
        if self.cache_path.exists():
            try:
                self.cache_path.unlink()
                _log.info("registry cache: cleared %s", self.cache_path)
                return True
            except Exception as e:
                _log.error("registry cache: failed to clear %s: %s",
                           self.cache_path, e)
                return False
        return False

    # ─────────── Freshness check ───────────

    def is_fresh(self, data: Optional[dict[str, Any]]) -> bool:
        """
        Return True if the cache still reflects the current state of
        commands/ and plugins/.

        Checks:
            - root dir mtime (commands/, plugins/)
            - each tracked file mtime + size
            - homer version (format may change)
        """
        if not data:
            return False
        if data.get("homer_version") != self._homer_version():
            _log.debug("registry cache: homer version changed, invalidating")
            return False

        # Root directory mtimes
        if not self._check_root_mtime(data, "commands_dir_mtime", self.commands_dir):
            return False
        if not self._check_root_mtime(data, "plugins_dir_mtime", self.plugins_dir):
            return False

        # Individual files
        for rel, info in (data.get("files") or {}).items():
            p = self.root / rel
            if not p.exists():
                _log.debug("registry cache: file gone %s", rel)
                return False
            try:
                st = p.stat()
            except OSError:
                return False
            if abs(st.st_mtime - info.get("mtime", 0)) > 0.001:
                _log.debug("registry cache: mtime changed %s", rel)
                return False
            if st.st_size != info.get("size", 0):
                _log.debug("registry cache: size changed %s", rel)
                return False

        return True

    def _check_root_mtime(
        self,
        data: dict[str, Any],
        key: str,
        path: Path,
    ) -> bool:
        stored = data.get(key)
        if stored is None:
            # Tracked dir was absent before. If it exists now, invalidate.
            if path.exists():
                _log.debug("registry cache: %s appeared, invalidating", path.name)
                return False
            return True
        if not path.exists():
            # Tracked dir disappeared -- invalidate only if we had content.
            _log.debug("registry cache: %s disappeared, invalidating", path.name)
            return True
        try:
            st = path.stat()
        except OSError:
            return False
        return abs(st.st_mtime - stored) <= 0.001

    # ─────────── Build snapshot ───────────

    def build_snapshot(
        self,
        *,
        commands: dict[str, dict[str, Any]],
        plugins: Optional[list[Any]] = None,
        langs_dirs: Optional[Iterable[Path]] = None,
    ) -> dict[str, Any]:
        """
        Build the cache dict from a full scan result.

        Commands without a 'path' (e.g. built-ins) are skipped: they
        are defined in code, not on the filesystem, so caching them
        gives no benefit and introduces a risk of stale metadata.
        """
        commands_mtime = (
            self.commands_dir.stat().st_mtime if self.commands_dir.exists() else None
        )
        plugins_mtime = (
            self.plugins_dir.stat().st_mtime if self.plugins_dir.exists() else None
        )

        files: dict[str, dict[str, Any]] = {}
        commands_dict: dict[str, dict[str, Any]] = {}

        for name, info in (commands or {}).items():
            # Skip built-ins and anything without a filesystem path.
            path_val = info.get("path")
            if not path_val:
                continue

            p = Path(path_val)
            if not p.is_absolute():
                p = self.root / p
            if not p.exists():
                continue

            try:
                st = p.stat()
            except OSError:
                continue

            rel = str(p.relative_to(self.root)).replace("\\", "/")
            commands_dict[name] = {
                "path": rel,
                "description": str(info.get("description") or ""),
                "source": str(info.get("source") or "user"),
            }
            files[rel] = {"mtime": st.st_mtime, "size": st.st_size}

        plugins_dict: dict[str, Any] = {}
        if plugins:
            for p in plugins:
                try:
                    rel = str(Path(p.path).relative_to(self.root)).replace("\\", "/")
                except (ValueError, AttributeError):
                    continue

                plugins_dict[p.name] = {
                    "path": rel,
                    "version": str(getattr(p, "version", "0.0.0")),
                    "requires": list(getattr(p, "requires", []) or []),
                    "requires_homer": str(getattr(p, "requires_homer", ">=1.0.0")),
                    "auto_migrate": bool(getattr(p, "auto_migrate", True)),
                    "has_commands": bool(getattr(p, "commands_dir", None)),
                    "has_langs": bool(getattr(p, "langs_dir", None)),
                    "has_migrations": bool(getattr(p, "migrations_dir", None)),
                    "has_templates": bool(getattr(p, "templates_dir", None)),
                    "has_static": bool(getattr(p, "static_dir", None)),
                    "has_email": bool(getattr(p, "email_dir", None)),
                    "has_lib": bool(getattr(p, "lib_dir", None)),
                }

                manifest = Path(p.path) / "plugin.json"
                if manifest.exists():
                    try:
                        st = manifest.stat()
                        rel_m = str(manifest.relative_to(self.root)).replace("\\", "/")
                        files[rel_m] = {"mtime": st.st_mtime, "size": st.st_size}
                    except OSError:
                        pass

        return {
            "version": CACHE_VERSION,
            "generated_at": datetime.now().isoformat(),
            "homer_version": self._homer_version(),
            "commands_dir_mtime": commands_mtime,
            "plugins_dir_mtime": plugins_mtime,
            "commands": commands_dict,
            "plugins": plugins_dict,
            "langs_dirs": [
                str(Path(d).relative_to(self.root)).replace("\\", "/")
                for d in (langs_dirs or [])
                if str(d).startswith(str(self.root))
            ],
            "files": files,
        }

    # ─────────── Introspection ───────────

    def stats(self) -> dict[str, Any]:
        """Return cache statistics without loading full content into memory."""
        if not self.cache_path.exists():
            return {
                "exists": False,
                "path": str(self.cache_path),
                "size": 0,
            }
        try:
            st = self.cache_path.stat()
        except OSError:
            return {"exists": False, "path": str(self.cache_path), "size": 0}

        data = self.load() or {}
        return {
            "exists": True,
            "path": str(self.cache_path),
            "size": st.st_size,
            "generated_at": data.get("generated_at"),
            "homer_version": data.get("homer_version"),
            "commands": len(data.get("commands") or {}),
            "plugins": len(data.get("plugins") or {}),
            "files_tracked": len(data.get("files") or {}),
            "fresh": self.is_fresh(data),
        }

    # ─────────── Helpers ───────────

    @staticmethod
    def _homer_version() -> str:
        try:
            return __version__
        except Exception:
            return "unknown"

# near the top, after _log

def _json_safe(value):
    """
    Return a value that can be encoded to JSON.
    Callables, modules and other non-serializable objects become str.
    Dicts and lists are processed recursively.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # callable, module, class, etc.
    return str(value)
