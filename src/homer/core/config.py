"""
Config loader with include support and optional caching.

Cache is NOT built automatically. To build it, run:

    ./homer config:cache

After that, subsequent command invocations use the cache when it is
fresh (mtime + size of every source file match). To clear:

    ./homer config:clear
"""

from __future__ import annotations

import glob
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

_log = logging.getLogger("homer.config")

CACHE_VERSION = 1


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


class Config:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self._cache_root = self.config_path.parent / "var" / "cache"
        self._cache_path = self._cache_root / "config.json"

        self._data: dict[str, Any] = {}
        self._source_files: list[Path] = []

        self.load()

    # ─────────── Public API ───────────

    @property
    def source_files(self) -> list[Path]:
        return list(self._source_files)

    @property
    def cache_path(self) -> Path:
        return self._cache_path

    def get(self, key: str, default: Any = None) -> Any:
        cur: Any = self._data
        for p in key.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
        return cur

    def all(self) -> dict[str, Any]:
        return self._data

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    # ─────────── Load / reload ───────────

    def load(self) -> None:
        """
        Load config.

        Order of attempts:
            1. Cache (if present and fresh) — no YAML parse.
            2. Full scan of source files.
        Cache is never written here.
        """
        cached = self._load_cache()
        if cached is not None and self._cache_is_fresh(cached):
            self._data = cached["data"]
            self._source_files = [
                Path(p) for p in cached.get("source_files", [])
            ]
            _log.debug("config: cache hit (%d files)", len(self._source_files))
            return

        self._full_load(save_cache=False)

    def reload(self) -> None:
        """
        Force full reload from disk. Called from SIGHUP handler in daemons.
        Cache is rebuilt only if it already existed.
        """
        _log.info("config: reload requested")
        cache_exists = self._cache_path.exists()
        self._full_load(save_cache=cache_exists)

    # ─────────── Cache management (called by config:cache) ───────────

    def build_cache(self) -> None:
        """Force full scan and save cache."""
        self._full_load(save_cache=True)

    def clear_cache(self) -> bool:
        if self._cache_path.exists():
            try:
                self._cache_path.unlink()
                _log.info("config: cache cleared")
                return True
            except Exception as e:
                _log.error("config: cache clear failed: %s", e)
                return False
        return False

    def cache_info(self) -> dict:
        """Return cache metadata."""
        if not self._cache_path.exists():
            return {"exists": False, "path": str(self._cache_path)}
        try:
            st = self._cache_path.stat()
        except OSError:
            return {"exists": False, "path": str(self._cache_path)}

        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return {
            "exists": True,
            "path": str(self._cache_path),
            "size": st.st_size,
            "generated_at": data.get("generated_at"),
            "source_files": len(data.get("source_files") or []),
            "fresh": self._cache_is_fresh(data) if data else False,
        }

    # ─────────── Full load ───────────

    def _full_load(self, *, save_cache: bool) -> None:
        if not self.config_path.exists():
            self._data = {}
            self._source_files = []
            _log.warning("config: %s not found", self.config_path)
            return

        try:
            main_data = self._read_yaml(self.config_path)
        except Exception as e:
            raise RuntimeError(f"Cannot read {self.config_path}: {e}") from e

        if not isinstance(main_data, dict):
            raise RuntimeError(
                f"{self.config_path}: top level must be a mapping"
            )

        includes = main_data.pop("_include", None) or []
        if isinstance(includes, str):
            includes = [includes]

        include_paths: list[Path] = []
        for pattern in includes:
            include_paths.extend(self._expand_include(pattern))

        seen: set[Path] = set()
        unique: list[Path] = []
        for p in include_paths:
            if p in seen:
                continue
            seen.add(p)
            unique.append(p)

        merged: dict[str, Any] = {}
        source_files: list[Path] = []

        for p in unique:
            try:
                data = self._read_yaml(p)
            except Exception as e:
                _log.warning("config: skipping %s: %s", p, e)
                continue
            if not isinstance(data, dict):
                _log.warning("config: %s top-level is not a mapping", p)
                continue
            _deep_merge(merged, data)
            source_files.append(p)

        _deep_merge(merged, main_data)
        source_files.append(self.config_path)

        self._data = merged
        self._source_files = source_files

        _log.info("config: loaded %d files", len(source_files))

        if save_cache:
            self._save_cache()

    def _expand_include(self, pattern: str) -> list[Path]:
        base = self.config_path.parent
        raw = Path(pattern)
        full_pattern = str(raw) if raw.is_absolute() else str(base / pattern)

        result: list[Path] = []
        for m in sorted(glob.glob(full_pattern, recursive=True)):
            p = Path(m)
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".yml", ".yaml"):
                continue
            if p == self.config_path:
                continue
            result.append(p)

        if not result:
            _log.warning("config: include pattern matched nothing: %s", pattern)
        return result

    @staticmethod
    def _read_yaml(path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # ─────────── Cache internals ───────────

    def _save_cache(self) -> None:
        try:
            self._cache_root.mkdir(parents=True, exist_ok=True)

            files_meta = []
            for p in self._source_files:
                try:
                    st = p.stat()
                except OSError:
                    continue
                rel = (
                    str(p.relative_to(self.config_path.parent))
                    if p.is_relative_to(self.config_path.parent)
                    else str(p)
                )
                files_meta.append({
                    "path": rel,
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                })

            payload = {
                "version": CACHE_VERSION,
                "generated_at": datetime.now().isoformat(),
                "config_path": str(self.config_path),
                "data": self._data,
                "source_files": [
                    str(p.relative_to(self.config_path.parent))
                    if p.is_relative_to(self.config_path.parent)
                    else str(p)
                    for p in self._source_files
                ],
                "files": files_meta,
            }

            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            tmp.replace(self._cache_path)
            _log.info("config: cache saved (%d files)", len(self._source_files))
        except Exception as e:
            _log.error("config: cache save failed: %s", e, exc_info=True)
            raise

    def _load_cache(self) -> Optional[dict]:
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("config: cache read failed: %s", e)
            return None
        if data.get("version") != CACHE_VERSION:
            return None
        if data.get("config_path") != str(self.config_path):
            return None
        return data

    def _cache_is_fresh(self, cached: dict) -> bool:
        base = self.config_path.parent
        for item in cached.get("files", []):
            rel = item.get("path")
            if not rel:
                return False
            p = Path(rel)
            if not p.is_absolute():
                p = base / rel
            if not p.exists():
                return False
            try:
                st = p.stat()
            except OSError:
                return False
            if abs(st.st_mtime - item.get("mtime", 0)) > 0.001:
                return False
            if st.st_size != item.get("size", 0):
                return False
        return True
