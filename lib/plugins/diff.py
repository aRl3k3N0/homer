"""
Diff между двумя состояниями плагина.

Источники «базового» состояния:
    1. plugins.lock (если есть) — то, что было зафиксировано.
    2. Git HEAD — если плагин в git-репозитории.
    3. Архив из release (не поддерживается сейчас).

Формат: unified diff по файлам + сводка.
"""
from __future__ import annotations

import difflib
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


EXCLUDE_DIRS = ('__pycache__', '.git', '.cache', '.mypy_cache',
                '.pytest_cache', '.ruff_cache')
EXCLUDE_SUFFIXES = ('.pyc', '.pyo', '.swp')


@dataclass
class FileDiff:
    status: str                    # 'added' | 'modified' | 'deleted'
    path: str                      # относительный путь от корня плагина
    old_size: Optional[int] = None
    new_size: Optional[int] = None
    old_checksum: Optional[str] = None
    new_checksum: Optional[str] = None
    unified: Optional[str] = None  # для text-файлов


@dataclass
class PluginDiff:
    plugin_name: str
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    files: list[FileDiff] = field(default_factory=list)
    migrations_added: list[str] = field(default_factory=list)
    migrations_removed: list[str] = field(default_factory=list)
    migrations_modified: list[str] = field(default_factory=list)
    requires_before: list[str] = field(default_factory=list)
    requires_after: list[str] = field(default_factory=list)
    requires_changed: bool = False
    source: str = ''               # 'lock' | 'git' | 'disk'


class PluginDiffer:
    def __init__(self, root_dir: Path, plugins_lock=None):
        """
        root_dir      — корень проекта
        plugins_lock  — экземпляр PluginsLock (опционально)
        """
        self.root = Path(root_dir)
        self.lock = plugins_lock

    # ─────────── Обнаружение источника ───────────

    def source_for(self, plugin_dir: Path) -> str:
        """
        Определяем, с чем сравнивать:
            - lock (если плагин есть в lock и checksum не совпадает)
            - git (если плагин внутри git-репозитория)
            - disk (fallback: без сравнения содержимого — только метаданные)
        """
        if self.lock and self.lock.exists():
            data = self.lock.load()
            has = any(p['name'] == plugin_dir.name
                      for p in data.get('plugins', []))
            if has:
                return 'lock'
        # git?
        try:
            proc = subprocess.run(
                ['git', 'rev-parse', '--is-inside-work-tree'],
                cwd=str(plugin_dir), capture_output=True,
                timeout=5, text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip() == 'true':
                return 'git'
        except Exception:
            pass
        return 'disk'

    # ─────────── Diff ───────────

    def diff(self, plugin_dir: Path,
             from_version: Optional[str] = None,
             to_version: Optional[str] = None,
             include_content_diff: bool = False,
             max_file_size: int = 1_000_000) -> PluginDiff:
        plugin_dir = Path(plugin_dir)
        source = self.source_for(plugin_dir)
        result = PluginDiff(
            plugin_name=plugin_dir.name,
            from_version=from_version,
            to_version=to_version,
            source=source,
        )

        # Метаданные плагина
        try:
            from .plugin import PluginInfo
            info = PluginInfo.from_dir(plugin_dir)
            if not result.to_version:
                result.to_version = info.version
            result.requires_after = list(info.requires or [])
        except Exception:
            info = None

        # Миграции — отдельно посчитаем
        self._diff_migrations(plugin_dir, result)

        if source == 'lock':
            self._diff_vs_lock(plugin_dir, result,
                               include_content_diff, max_file_size)
            # requires из lock
            data = self.lock.load()
            lp = next((p for p in data.get('plugins', [])
                       if p['name'] == plugin_dir.name), None)
            if lp:
                result.requires_before = list(lp.get('requires') or [])
                if not result.from_version:
                    result.from_version = lp.get('version')
            result.requires_changed = (
                sorted(result.requires_before) != sorted(result.requires_after)
            )
        elif source == 'git':
            self._diff_vs_git(plugin_dir, result,
                              include_content_diff, max_file_size)
        else:
            # Не с чем сравнивать — только отчёт по метаданным
            pass

        return result

    # ─────────── vs lock ───────────

    def _diff_vs_lock(self, plugin_dir: Path, result: PluginDiff,
                      include_content_diff: bool, max_file_size: int):
        data = self.lock.load()
        lp = next((p for p in data.get('plugins', [])
                   if p['name'] == plugin_dir.name), None)
        if not lp:
            return

        # У нас в lock нет полного дерева файлов, только общий checksum и
        # миграции. Полное diff сделать нельзя, поэтому сообщаем, что
        # общий checksum изменился.

        # Проверим миграции (по именам + checksums)
        for m in lp.get('migrations', []):
            file = plugin_dir / 'migrations' / m['driver'] / m['file']
            if not file.exists():
                result.migrations_removed.append(f"{m['driver']}/{m['file']}")
                continue
            cur = self._hash_file(file)
            if cur != m['checksum']:
                result.migrations_modified.append(f"{m['driver']}/{m['file']}")

    # ─────────── vs git ───────────

    def _diff_vs_git(self, plugin_dir: Path, result: PluginDiff,
                     include_content_diff: bool, max_file_size: int):
        """
        Сравниваем текущий рабочий каталог с HEAD (или с указанным коммитом).
        """
        # --name-status даёт статусы A/M/D
        try:
            proc = subprocess.run(
                ['git', 'diff', '--name-status', 'HEAD', '--', '.'],
                cwd=str(plugin_dir), capture_output=True,
                timeout=30, text=True,
            )
        except Exception:
            return

        if proc.returncode != 0:
            return

        for line in proc.stdout.splitlines():
            parts = line.split('\t', 1)
            if len(parts) != 2:
                continue
            status_raw, path = parts
            status = status_raw[0].lower()  # 'a','m','d','r',...
            if status == 'r':
                # rename: A\tB — пропускаем детально
                status = 'modified'
            if status not in ('a', 'm', 'd'):
                status = 'modified'

            # Игнорируем мусор
            if any(part in EXCLUDE_DIRS for part in Path(path).parts):
                continue
            if Path(path).suffix in EXCLUDE_SUFFIXES:
                continue

            fd = FileDiff(
                status={'a': 'added', 'm': 'modified', 'd': 'deleted'}[status],
                path=path,
            )

            # Содержимое
            if include_content_diff and status in ('a', 'm'):
                fd.unified = self._git_content_diff(plugin_dir, path,
                                                    status == 'a')
            result.files.append(fd)

    def _git_content_diff(self, plugin_dir: Path, path: str,
                          is_new: bool) -> Optional[str]:
        try:
            if is_new:
                # Файл не в HEAD — показываем его целиком
                p = plugin_dir / path
                if not p.exists():
                    return None
                text = p.read_text(encoding='utf-8', errors='replace')
                lines = text.splitlines(keepends=True)
                return ''.join(difflib.unified_diff(
                    [], lines,
                    fromfile='/dev/null',
                    tofile=f'b/{path}',
                ))
            proc = subprocess.run(
                ['git', 'diff', 'HEAD', '--', path],
                cwd=str(plugin_dir), capture_output=True,
                timeout=30, text=True,
            )
            return proc.stdout or None
        except Exception:
            return None

    # ─────────── Миграции ───────────

    def _diff_migrations(self, plugin_dir: Path, result: PluginDiff):
        """
        Отдельный diff по миграциям: показываем новые/удалённые/изменённые
        относительно lock (если есть).
        """
        if not self.lock or not self.lock.exists():
            return

        data = self.lock.load()
        lp = next((p for p in data.get('plugins', [])
                   if p['name'] == plugin_dir.name), None)
        if not lp:
            return

        locked_migs = {
            (m['driver'], m['file']): m['checksum']
            for m in lp.get('migrations', [])
        }

        mig_dir = plugin_dir / 'migrations'
        if not mig_dir.exists():
            return

        current_migs = {}
        for driver_dir in mig_dir.iterdir():
            if not driver_dir.is_dir():
                continue
            if driver_dir.name.startswith(('upgrade_', 'downgrade_')):
                continue
            driver = driver_dir.name
            for f in driver_dir.glob('*.sql'):
                current_migs[(driver, f.name)] = self._hash_file(f)

        for key in current_migs:
            if key not in locked_migs:
                result.migrations_added.append(f"{key[0]}/{key[1]}")
            elif current_migs[key] != locked_migs[key]:
                if f"{key[0]}/{key[1]}" not in result.migrations_modified:
                    result.migrations_modified.append(f"{key[0]}/{key[1]}")

        for key in locked_migs:
            if key not in current_migs:
                if f"{key[0]}/{key[1]}" not in result.migrations_removed:
                    result.migrations_removed.append(f"{key[0]}/{key[1]}")

    # ─────────── Утилиты ───────────

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()
