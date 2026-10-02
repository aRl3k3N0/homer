"""
Dependency lock для плагинов.

Файл: plugins.lock в корне проекта.

Содержит:
    version          — версия формата
    generated_at     — когда сгенерировано
    homer_version    — версия Homer на момент генерации
    plugins          — {name: {version, requires, checksum, migrations, files_count}}
    migrations       — {<plugin>:<driver>:<file>: {checksum, applied_at}}

Используется для:
    - воспроизводимости окружения (как requirements.lock)
    - быстрой проверки целостности (plugin:audit)
    - предупреждения при изменениях в миграциях после релиза
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

LOCK_VERSION = 1


@dataclass
class LockedMigration:
    plugin: str
    driver: str
    file: str
    checksum: str
    applied_at: Optional[str] = None


@dataclass
class LockedPlugin:
    name: str
    version: str
    requires: list[str] = field(default_factory=list)
    checksum: str = ''
    files_count: int = 0
    state: str = 'enabled'
    migrations: list[LockedMigration] = field(default_factory=list)


class PluginsLock:
    def __init__(self, root_dir: Path):
        self.root = Path(root_dir)
        self.path = self.root / 'plugins.lock'
        self._data: dict[str, Any] = {}

    # ─────────── Чтение/запись ───────────

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict:
        if not self.path.exists():
            self._data = self._empty()
            return self._data
        try:
            self._data = json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            self._data = self._empty()
        return self._data

    def save(self, homer_version: str, plugins: list):
        """Сохраняет lock-файл по текущему состоянию."""
        self.load()

        locked_plugins = []
        locked_migrations: dict[str, dict] = {}

        # Прочитаем информацию о применённых миграциях из БД
        # (см. update_from_db)

        for p in plugins:
            files_checksum = self._hash_plugin(p.path)
            files_count = sum(1 for f in p.path.rglob('*') if f.is_file())

            migrations = []
            for driver_dir in p.migrations_dir.iterdir() if p.migrations_dir else []:
                if not driver_dir.is_dir():
                    continue
                driver = driver_dir.name
                for sql in sorted(driver_dir.glob('*.sql')):
                    checksum = self._hash_file(sql)
                    migrations.append(
                        LockedMigration(
                            plugin=p.name,
                            driver=driver,
                            file=sql.name,
                            checksum=checksum,
                            applied_at=None,  # заполняется update_from_db
                        )
                    )

            locked_plugins.append(
                LockedPlugin(
                    name=p.name,
                    version=p.version,
                    requires=list(p.requires or []),
                    checksum=files_checksum,
                    files_count=files_count,
                    state=p.state,
                    migrations=migrations,
                )
            )

        self._data = {
            'version': LOCK_VERSION,
            'generated_at': datetime.now().isoformat(),
            'homer_version': homer_version,
            'plugins': [asdict(p) for p in locked_plugins],
        }
        self._write()

    def update_from_db(self, driver: str, db):
        """
        Читает homer_plugin_migrations и homer_plugin_state,
        заполняет applied_at в lock-файле.
        """
        # applied_at
        try:
            rows = db.fetchall(
                f"SELECT plugin_name, driver, migration_name, applied_at "
                f"FROM homer_plugin_migrations WHERE driver = "
                f"{self._ph(db, 0)}",
                [driver],
                dictionary=True,
            )
            applied = {}
            for r in rows:
                d = (
                    r
                    if isinstance(r, dict)
                    else {
                        'plugin_name': r[0],
                        'driver': r[1],
                        'migration_name': r[2],
                        'applied_at': r[3],
                    }
                )
                key = f"{d['plugin_name']}|{d['driver']}|{d['migration_name']}"
                applied[key] = d['applied_at']
        except Exception:
            applied = {}

        # installed_version
        try:
            rows = db.fetchall(
                "SELECT plugin_name, installed_version, "
                "installed_at, updated_at FROM homer_plugin_state",
                dictionary=True,
            )
            state = {}
            for r in rows:
                d = (
                    r
                    if isinstance(r, dict)
                    else {
                        'plugin_name': r[0],
                        'installed_version': r[1],
                        'installed_at': r[2],
                        'updated_at': r[3],
                    }
                )
                state[d['plugin_name']] = d
        except Exception:
            state = {}

        for p in self._data.get('plugins', []):
            pname = p['name']
            if pname in state:
                p['installed_version'] = state[pname].get('installed_version')
                p['installed_at'] = self._iso(state[pname].get('installed_at'))
            for m in p.get('migrations', []):
                key = f"{m['plugin']}|{m['driver']}|{m['file']}"
                if key in applied:
                    m['applied_at'] = self._iso(applied[key])

        self._write()

    # ─────────── Проверка целостности ───────────

    def verify(self, plugins: list, drivers: list[str]) -> list[dict]:
        """
        Сверяет текущее состояние с lock-файлом.
        Возвращает список расхождений.
        """
        if not self._data:
            self.load()

        issues = []
        locked = {p['name']: p for p in self._data.get('plugins', [])}
        current = {p.name: p for p in plugins}

        # Отсутствующие/лишние
        for name in locked:
            if name not in current:
                issues.append(
                    {
                        'type': 'missing',
                        'plugin': name,
                        'message': f"Плагин '{name}' есть в lock, но не установлен",
                    }
                )
        for name in current:
            if name not in locked:
                issues.append(
                    {
                        'type': 'extra',
                        'plugin': name,
                        'message': f"Плагин '{name}' установлен, но нет в lock",
                    }
                )

        # Версии/checksums
        for name, p in current.items():
            l = locked.get(name)
            if not l:
                continue
            if l['version'] != p.version:
                issues.append(
                    {
                        'type': 'version',
                        'plugin': name,
                        'message': (f"Версия изменилась: {l['version']} → {p.version}"),
                    }
                )

            # Checksum файлов
            current_checksum = self._hash_plugin(p.path)
            if l.get('checksum') and l['checksum'] != current_checksum:
                issues.append(
                    {
                        'type': 'files_changed',
                        'plugin': name,
                        'message': f"Содержимое плагина '{name}' изменилось",
                    }
                )

            # Миграции: состав
            locked_migs = {(m['driver'], m['file']): m['checksum'] for m in l.get('migrations', [])}
            for driver in drivers:
                ddir = (p.migrations_dir / driver) if p.migrations_dir else None
                if not ddir or not ddir.exists():
                    continue
                for sql in ddir.glob('*.sql'):
                    key = (driver, sql.name)
                    cur_cs = self._hash_file(sql)
                    if key not in locked_migs:
                        issues.append(
                            {
                                'type': 'migration_added',
                                'plugin': name,
                                'message': (
                                    f"Новая миграция {driver}/{sql.name} не отражена в lock"
                                ),
                            }
                        )
                    elif locked_migs[key] != cur_cs:
                        issues.append(
                            {
                                'type': 'migration_changed',
                                'plugin': name,
                                'message': (
                                    f"Миграция {driver}/{sql.name} изменена после фиксации в lock"
                                ),
                            }
                        )

            # Лишние миграции в lock
            for driver, file in locked_migs:
                if driver not in drivers:
                    continue
                ddir = (p.migrations_dir / driver) if p.migrations_dir else None
                if not ddir or not (ddir / file).exists():
                    issues.append(
                        {
                            'type': 'migration_removed',
                            'plugin': name,
                            'message': (f"Миграция {driver}/{file} есть в lock, но отсутствует"),
                        }
                    )

        return issues

    # ─────────── Утилиты ───────────

    def _empty(self) -> dict:
        return {
            'version': LOCK_VERSION,
            'generated_at': None,
            'homer_version': None,
            'plugins': [],
        }

    def _write(self):
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    def _hash_plugin(self, plugin_dir: Path) -> str:
        """
        Checksum содержимого плагина: hash от отсортированных
        (rel_path, file_hash). Исключаем __pycache__, .git, *.pyc.
        """
        items = []
        for f in sorted(plugin_dir.rglob('*')):
            if not f.is_file():
                continue
            rel = f.relative_to(plugin_dir)
            if any(part in ('__pycache__', '.git', '.cache') for part in rel.parts):
                continue
            if f.suffix in ('.pyc', '.pyo'):
                continue
            items.append((str(rel).replace('\\', '/'), self._hash_file(f)))

        h = hashlib.sha256()
        for rel, ch in items:
            h.update(rel.encode('utf-8'))
            h.update(b'\0')
            h.update(ch.encode('utf-8'))
            h.update(b'\n')
        return h.hexdigest()

    @staticmethod
    def _iso(v):
        if v is None:
            return None
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return str(v)

    @staticmethod
    def _ph(db, idx: int) -> str:
        style = getattr(db, '_placeholder_style', '%s')
        if style == ':name':
            return f':{idx + 1}'
        if style == '?':
            return '?'
        return '%s'
