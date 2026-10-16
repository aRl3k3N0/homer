"""
Safe file editor for paths inside the project.

Only files under the whitelist of the configured paths can be edited:
    - config_dir       (config.yml + config/ includes)
    - commands_dir
    - plugins_dir
    - langs_dir
    - templates_dir
    - static_dir

Each operation checks:
    - path is inside an allowed root
    - path is not a symlink pointing outside
    - file size under limit
    - no path traversal
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from homer.core.paths import Paths


class EditorError(Exception):
    pass


class PermissionDenied(EditorError):
    pass


class ConflictError(EditorError):
    pass


@dataclass
class FileInfo:
    path: str                 # relative to base
    absolute: str
    name: str
    size: int
    mtime: float
    checksum: str
    category: str             # 'config' | 'commands' | 'plugins' | 'langs' | ...


class FileEditor:
    """
    Read/write files inside allowed roots only.

    `category` -- logical group ('config', 'commands', 'plugins',
    'langs', 'templates', 'static') that maps to a configured path.
    """

    MAX_SIZE = 2 * 1024 * 1024        # 2 MB

    def __init__(self, paths: Paths):
        self.paths = paths
        self.roots = {
            "config":    paths.config_path.parent,
            "commands":  paths.commands_dir,
            "plugins":   paths.plugins_dir,
            "langs":     paths.langs_dir,
            "templates": paths.templates_dir,
            "static":    paths.static_dir,
            # Also allow the project's email templates dir
            "email":     paths.email_templates_dir,
        }

    # ─────────── Path safety ───────────

    def _resolve_root(self, category: str) -> Path:
        root = self.roots.get(category)
        if not root:
            raise EditorError(f"Unknown category '{category}'")
        return root.resolve()

    def _resolve(self, category: str, rel_path: str,
                 *, must_exist: bool = True) -> Path:
        """
        Resolve `rel_path` inside `category` root.
        Blocks path traversal and symlink escapes.
        """
        root = self._resolve_root(category)
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise PermissionDenied(f"Unsafe path: {rel_path}")

        candidate = (root / rel).resolve()
        if not str(candidate).startswith(str(root)):
            raise PermissionDenied(f"Path escapes root: {rel_path}")

        if must_exist and not candidate.exists():
            raise EditorError(f"File not found: {rel_path}")

        return candidate

    # ─────────── Read ───────────

    def info(self, category: str, rel_path: str) -> FileInfo:
        p = self._resolve(category, rel_path)
        st = p.stat()
        if st.st_size > self.MAX_SIZE:
            raise EditorError(f"File too large ({st.st_size} bytes)")
        return FileInfo(
            path=str(p.relative_to(self._resolve_root(category))),
            absolute=str(p),
            name=p.name,
            size=st.st_size,
            mtime=st.st_mtime,
            checksum=self._checksum(p),
            category=category,
        )

    def read(self, category: str, rel_path: str) -> tuple[FileInfo, str]:
        info = self.info(category, rel_path)
        p = self._resolve(category, rel_path)
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise EditorError("File is not UTF-8 text")
        return info, text

    # ─────────── Write ───────────

    def write(self, category: str, rel_path: str, content: str,
              *, expected_checksum: Optional[str] = None,
              create: bool = False) -> FileInfo:
        """
        Write `content` to a file.

        If expected_checksum is provided, it must match the current file
        checksum; otherwise ConflictError is raised (someone else saved
        between read and write).
        """
        p = self._resolve(category, rel_path, must_exist=not create)

        if not create and expected_checksum:
            current = self._checksum(p)
            if current != expected_checksum:
                raise ConflictError(
                    "File changed since you opened it. "
                    "Reload and try again."
                )

        if len(content.encode("utf-8")) > self.MAX_SIZE:
            raise EditorError("Content too large")

        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, p)

        return self.info(category, rel_path)

    def delete(self, category: str, rel_path: str) -> None:
        p = self._resolve(category, rel_path)
        if not p.is_file():
            raise EditorError("Not a file")
        p.unlink()

    def mkdir(self, category: str, rel_path: str) -> None:
        p = self._resolve(category, rel_path, must_exist=False)
        p.mkdir(parents=True, exist_ok=True)

    # ─────────── List ───────────

    def list_tree(self, category: str, subpath: str = "",
                  pattern: str = "*") -> list[dict]:
        """
        Return a tree of files and directories under the category root
        (or subpath). Directories first, then files, alphabetically.
        """
        root = self._resolve_root(category)
        base = self._resolve(category, subpath, must_exist=False) \
            if subpath else root
        if not base.exists():
            return []
        if base.is_file():
            return [self._file_entry(base, root)]

        entries = []
        try:
            for entry in sorted(base.iterdir(),
                                key=lambda p: (not p.is_dir(), p.name.lower())):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    entries.append(self._dir_entry(entry, root))
                elif entry.match(pattern):
                    entries.append(self._file_entry(entry, root))
        except PermissionError:
            pass
        return entries

    def _file_entry(self, p: Path, root: Path) -> dict:
        st = p.stat()
        return {
            "type": "file",
            "name": p.name,
            "path": str(p.relative_to(root)),
            "size": st.st_size,
            "mtime": st.st_mtime,
        }

    def _dir_entry(self, p: Path, root: Path) -> dict:
        st = p.stat()
        children_count = 0
        try:
            children_count = sum(1 for _ in p.iterdir())
        except Exception:
            pass
        return {
            "type": "dir",
            "name": p.name,
            "path": str(p.relative_to(root)),
            "mtime": st.st_mtime,
            "children_count": children_count,
        }

    # ─────────── Helpers ───────────

    @staticmethod
    def _checksum(p: Path) -> str:
        h = hashlib.sha256()
        h.update(p.read_bytes())
        return h.hexdigest()
