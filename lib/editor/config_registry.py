"""
Config registry: flat, key-value view of the merged config,
with section operations on top.

Data model:
    key path       e.g. "databases.postgres.host"
    section path   e.g. "databases.postgres" (a mapping, not a leaf)
    leaf           a scalar / list / null (a key with a value)

Sections are implicit: any prefix of an existing key that is a mapping.
We allow creating empty sections by writing `{}` at a key path.

Writes preserve file structure (comments, order) when ruamel.yaml
is installed; otherwise PyYAML rewrites the whole file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from ruamel.yaml import YAML
    _HAS_RUAMEL = True
except ImportError:
    _HAS_RUAMEL = False
    import yaml


class ConfigRegistryError(Exception):
    pass


@dataclass
class ConfigEntry:
    path: str
    value: Any
    type: str
    source: str
    line: Optional[int] = None
    locked_by: Optional[str] = None


class ConfigRegistry:
    def __init__(self, config, paths):
        self.config = config
        self.paths = paths
        self.config_path = paths.config_path
        self._yaml = self._make_yaml()

    # ─────────── YAML IO ───────────

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

    def list_sections(self) -> list[str]:
        """
        Return every section path (mapping) in the merged config,
        including empty ones. Always includes the root as ''.
        """
        merged = self.config.all()
        out: set[str] = {""}
        self._collect_sections(merged, "", out)
        return sorted(out)

    def list_leaves_of(self, section: str) -> list[ConfigEntry]:
        """
        Return entries whose immediate parent is `section`.
        """
        merged = self.config.all()
        node = self._get_by_path(merged, section) if section else merged
        if not isinstance(node, dict):
            return []
        source_map = self._build_source_map()
        out: list[ConfigEntry] = []
        for k, v in node.items():
            key = f"{section}.{k}" if section else str(k)
            if isinstance(v, dict):
                continue  # it is a section, not a leaf
            out.append(ConfigEntry(
                path=key,
                value=v,
                type=self._type_of(v),
                source=self._relative(source_map.get(key) or ""),
            ))
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
            source=self._relative(source) if source else "",
        )

    # ─────────── Mutations ───────────

    def set(self, key_path: str, value: Any, *, expected_value: Any = None):
        merged = self.config.all()
        current = self._get_by_path(merged, key_path)
        if current is _MISSING:
            raise ConfigRegistryError(f"Unknown key: {key_path}")
        if expected_value is not None and current != expected_value:
            raise ConfigRegistryError(
                f"Value changed since you opened it "
                f"(was {current!r}, expected {expected_value!r})"
            )
        source = self._find_source(key_path) or self.config_path
        doc = self._load_doc(source)
        self._set_by_path(doc, key_path, value)
        self._save_doc(source, doc)
        self.config.reload()
        return self.get(key_path)

    def create_value(self, key_path: str, value: Any):
        """
        Create a new leaf. Parent section must exist (implicitly).
        """
        if self._get_by_path(self.config.all(), key_path) is not _MISSING:
            raise ConfigRegistryError(f"Key already exists: {key_path}")
        parent = ".".join(key_path.split(".")[:-1])
        # Choose a source file: if parent section exists in one source,
        # add the leaf there; otherwise default to config.yml.
        source = self._find_source(parent) if parent else None
        source = source or self.config_path
        doc = self._load_doc(source)
        self._set_by_path(doc, key_path, value)
        self._save_doc(source, doc)
        self.config.reload()
        return self.get(key_path)

    def create_section(self, section_path: str):
        """
        Create an empty section (writes `{}` at the path).
        """
        if self._get_by_path(self.config.all(), section_path) is not _MISSING:
            raise ConfigRegistryError(f"Section already exists: {section_path}")
        parent = ".".join(section_path.split(".")[:-1])
        source = self._find_source(parent) if parent else None
        source = source or self.config_path
        doc = self._load_doc(source)
        self._set_by_path(doc, section_path, {})
        self._save_doc(source, doc)
        self.config.reload()

    def rename(self, old_path: str, new_path: str):
        """
        Rename a value or a section. The parent stays the same;
        the last segment changes.
        """
        old_value = self._get_by_path(self.config.all(), old_path)
        if old_value is _MISSING:
            raise ConfigRegistryError(f"Not found: {old_path}")
        if self._get_by_path(self.config.all(), new_path) is not _MISSING:
            raise ConfigRegistryError(f"Already exists: {new_path}")

        source = self._find_source(old_path) or self.config_path
        doc = self._load_doc(source)
        self._delete_by_path(doc, old_path)
        self._set_by_path(doc, new_path, old_value)
        self._save_doc(source, doc)
        self.config.reload()

    def delete(self, key_path: str):
        merged = self.config.all()
        if self._get_by_path(merged, key_path) is _MISSING:
            raise ConfigRegistryError(f"Unknown key: {key_path}")
        source = self._find_source(key_path) or self.config_path
        doc = self._load_doc(source)
        self._delete_by_path(doc, key_path)
        self._save_doc(source, doc)
        self.config.reload()

    def delete_section(self, section_path: str):
        """
        Delete a section. Only allowed if it is empty (no leaves,
        no subsections).
        """
        if not section_path:
            raise ConfigRegistryError("Cannot delete root")
        node = self._get_by_path(self.config.all(), section_path)
        if node is _MISSING:
            raise ConfigRegistryError(f"Not found: {section_path}")
        if not isinstance(node, dict):
            raise ConfigRegistryError(f"Not a section: {section_path}")
        if node:
            raise ConfigRegistryError(
                f"Section '{section_path}' is not empty; "
                f"delete its children first"
            )
        source = self._find_source(section_path) or self.config_path
        doc = self._load_doc(source)
        self._delete_by_path(doc, section_path)
        self._save_doc(source, doc)
        self.config.reload()

    # ─────────── Internals ───────────

    def _flatten(self, obj, prefix, out, source_map):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    self._flatten(v, key, out, source_map)
                else:
                    out.append(ConfigEntry(
                        path=key,
                        value=v,
                        type=self._type_of(v),
                        source=self._relative(source_map.get(key) or ""),
                    ))

    def _collect_sections(self, obj, prefix, out):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    out.add(key)
                    self._collect_sections(v, key, out)

    def _relative(self, path: Any) -> str:
        if not path:
            return ""
        try:
            return str(Path(path).relative_to(self.paths.base))
        except Exception:
            return str(path)

    def _type_of(self, v: Any) -> str:
        if v is None: return "null"
        if isinstance(v, bool): return "bool"
        if isinstance(v, int): return "int"
        if isinstance(v, float): return "float"
        if isinstance(v, str): return "string"
        if isinstance(v, list): return "list"
        if isinstance(v, dict): return "dict"
        return type(v).__name__

    def _get_by_path(self, obj, path):
        if not path:
            return obj
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return _MISSING
        return cur

    def _set_by_path(self, obj, path, value):
        parts = path.split(".")
        cur = obj
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    def _delete_by_path(self, obj, path):
        parts = path.split(".")
        cur = obj
        for part in parts[:-1]:
            if not isinstance(cur, dict) or part not in cur:
                return
            cur = cur[part]
        if isinstance(cur, dict) and parts[-1] in cur:
            del cur[parts[-1]]

    def _find_source(self, key_path: str) -> Optional[Path]:
        for src in self.config.source_files:
            try:
                doc = self._load_doc(src)
            except Exception:
                continue
            if self._get_by_path(doc, key_path) is not _MISSING:
                return src
        return None

    def _build_source_map(self) -> dict:
        result: dict[str, Path] = {}
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
