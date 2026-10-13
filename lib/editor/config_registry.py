"""
Config registry: a flat, key-value view of the merged config.

Each entry:
    {
        "path": "databases.postgres.host",
        "value": "localhost",
        "type": "string" | "int" | "float" | "bool" | "null" | "list" | "dict",
        "source": "config.yml" | "config/idm/db.yml" | ...,
        "line": 12,                 # line number in the source file (if found)
        "locked_by": "admin",       # optional lock info
    }

The registry is built from:
    - the merged config (via Config)
    - the source files tracked by Config.source_files

The editor can:
    - list all keys (flat or as a tree)
    - read one key
    - set one key (writes back to the correct source file)
    - delete one key

Writes preserve file structure (comments, order) by using ruamel.yaml
instead of PyYAML. If ruamel is not installed, we fall back to
plain PyYAML and rewrite the whole file — comments will be lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    _HAS_RUAMEL = True
except ImportError:
    _HAS_RUAMEL = False
    import yaml


class ConfigRegistryError(Exception):
    pass


@dataclass
class ConfigEntry:
    path: str                     # dotted path
    value: Any
    type: str                     # string/int/float/bool/null/list/dict
    source: str                   # file name (relative to project)
    line: Optional[int] = None
    locked_by: Optional[str] = None


class ConfigRegistry:
    def __init__(self, config, paths):
        self.config = config
        self.paths = paths
        self.config_path = paths.config_path
        self._yaml = self._make_yaml()

    # ─────────── YAML IO (ruamel if available) ───────────

    @staticmethod
    def _make_yaml():
        if not _HAS_RUAMEL:
            return None
        y = YAML()
        y.preserve_quotes = True
        y.indent(mapping=2, sequence=4, offset=2)
        return y

    def _load_doc(self, path: Path):
        if self._yaml:
            with open(path, "r", encoding="utf-8") as f:
                return self._yaml.load(f) or {}
        import yaml as _yaml
        with open(path, "r", encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}

    def _save_doc(self, path: Path, doc):
        # Atomic
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            if self._yaml:
                self._yaml.dump(doc, f)
            else:
                import yaml as _yaml
                _yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
        tmp.replace(path)

    # ─────────── Registry view ───────────

    def list_entries(self) -> list[ConfigEntry]:
        merged = self.config.all()
        source_map = self._build_source_map()
        out: list[ConfigEntry] = []
        self._flatten(merged, "", out, source_map)
        out.sort(key=lambda e: e.path)
        return out

    def get(self, key_path: str) -> Optional[ConfigEntry]:
        merged = self.config.all()
        value = self._get_by_path(merged, key_path)
        if value is _MISSING:
            return None
        source = self._find_source(key_path)
        return ConfigEntry(
            path=key_path,
            value=value,
            type=self._type_of(value),
            source=str(source.relative_to(self.paths.base))
                    if source else "(unknown)",
        )

    def set(self, key_path: str, value: Any, *, expected_value: Any = None):
        """
        Set key. If expected_value is given, the current merged value
        must equal it, otherwise ConfigRegistryError is raised
        (someone else changed it since you opened the registry).
        """
        merged = self.config.all()
        current = self._get_by_path(merged, key_path)
        if current is _MISSING:
            raise ConfigRegistryError(f"Unknown key: {key_path}")
        if expected_value is not None and current != expected_value:
            raise ConfigRegistryError(
                f"Value changed since you opened it "
                f"(was {current!r}, expected {expected_value!r})"
            )

        # Find source file and write there
        source = self._find_source(key_path) or self.config_path
        doc = self._load_doc(source)
        self._set_by_path(doc, key_path, value)
        self._save_doc(source, doc)
        # Reload merged config
        self.config.reload()
        return self.get(key_path)

    def delete(self, key_path: str):
        merged = self.config.all()
        if self._get_by_path(merged, key_path) is _MISSING:
            raise ConfigRegistryError(f"Unknown key: {key_path}")
        source = self._find_source(key_path) or self.config_path
        doc = self._load_doc(source)
        self._delete_by_path(doc, key_path)
        self._save_doc(source, doc)
        self.config.reload()

    # ─────────── Internals ───────────

    def _flatten(self, obj, prefix: str, out: list, source_map: dict):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, (dict, list)):
                    if isinstance(v, dict):
                        self._flatten(v, key, out, source_map)
                    else:
                        out.append(ConfigEntry(
                            path=key,
                            value=v,
                            type="list",
                            source=self._relative(source_map.get(key) or ""),
                        ))
                else:
                    out.append(ConfigEntry(
                        path=key,
                        value=v,
                        type=self._type_of(v),
                        source=self._relative(source_map.get(key) or ""),
                    ))

    def _relative(self, path: Any) -> str:
        if not path:
            return ""
        try:
            return str(Path(path).relative_to(self.paths.base))
        except Exception:
            return str(path)

    def _type_of(self, v: Any) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, int):
            return "int"
        if isinstance(v, float):
            return "float"
        if isinstance(v, str):
            return "string"
        if isinstance(v, list):
            return "list"
        if isinstance(v, dict):
            return "dict"
        return type(v).__name__

    def _get_by_path(self, obj, path: str):
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return _MISSING
        return cur

    def _set_by_path(self, obj, path: str, value):
        parts = path.split(".")
        cur = obj
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    def _delete_by_path(self, obj, path: str):
        parts = path.split(".")
        cur = obj
        for part in parts[:-1]:
            if not isinstance(cur, dict) or part not in cur:
                return
            cur = cur[part]
        if isinstance(cur, dict) and parts[-1] in cur:
            del cur[parts[-1]]

    def _find_source(self, key_path: str) -> Optional[Path]:
        """
        Find which source file contains this key (best-effort).
        Uses source_files of the Config; falls back to config_path.
        """
        for src in self.config.source_files:
            try:
                doc = self._load_doc(src)
            except Exception:
                continue
            if self._get_by_path(doc, key_path) is not _MISSING:
                return src
        return None

    def _build_source_map(self) -> dict:
        """Return {key_path: Path} for every key in every source file."""
        result = {}
        for src in self.config.source_files:
            try:
                doc = self._load_doc(src)
            except Exception:
                continue
            self._walk_source(doc, "", result, src)
        return result

    def _walk_source(self, obj, prefix, out, src):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    self._walk_source(v, key, out, src)
                else:
                    out.setdefault(key, src)


_MISSING = object()
