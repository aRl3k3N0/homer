"""Apply built-in and project SQL migrations."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any

from .sql import normalize_driver, split_sql

_MIGRATION_FILENAME = re.compile(r'^(\d+)_([a-zA-Z0-9_-]+)\.sql$')

MIGRATION_DDL = {
    'sqlite': """
        CREATE TABLE IF NOT EXISTS homer_migrations (
            migration_source TEXT NOT NULL,
            driver           TEXT NOT NULL,
            migration_name   TEXT NOT NULL,
            applied_at       TEXT NOT NULL,
            checksum         TEXT,
            PRIMARY KEY (migration_source, driver, migration_name)
        )
    """,
    'postgres': """
        CREATE TABLE IF NOT EXISTS homer_migrations (
            migration_source VARCHAR(32) NOT NULL,
            driver           VARCHAR(64) NOT NULL,
            migration_name   VARCHAR(255) NOT NULL,
            applied_at       TIMESTAMP NOT NULL,
            checksum         VARCHAR(64),
            PRIMARY KEY (migration_source, driver, migration_name)
        )
    """,
    'oracle': """
        BEGIN
            EXECUTE IMMEDIATE '
                CREATE TABLE homer_migrations (
                    migration_source VARCHAR2(32) NOT NULL,
                    driver           VARCHAR2(64) NOT NULL,
                    migration_name   VARCHAR2(255) NOT NULL,
                    applied_at       TIMESTAMP NOT NULL,
                    checksum         VARCHAR2(64),
                    CONSTRAINT pk_homer_migrations PRIMARY KEY
                        (migration_source, driver, migration_name)
                )';
        EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
        END;
    """,
    'mysql': """
        CREATE TABLE IF NOT EXISTS homer_migrations (
            migration_source VARCHAR(32) NOT NULL,
            driver           VARCHAR(64) NOT NULL,
            migration_name   VARCHAR(255) NOT NULL,
            applied_at       DATETIME NOT NULL,
            checksum         VARCHAR(64),
            PRIMARY KEY (migration_source, driver, migration_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
}

SUPPORTED_DRIVERS = frozenset(
    {
        'sqlite',
        'postgres',
        'postgresql',
        'oracle',
        'mysql',
        'mariadb',
    }
)
_TRANSACTIONAL_DDL_DRIVERS = frozenset({'sqlite', 'postgres'})


class MigrationError(RuntimeError):
    """Raised when a migration cannot be safely applied."""


class MigrationRunner:
    """Run numbered SQL files from Homer and the current project.

    Built-in migrations live in ``lib/migrations/<driver>``. Project-owned
    migrations live in ``<root_dir>/migrations/<driver>``. The ledger records
    each source separately, so a project migration may reuse a built-in name.
    """

    def __init__(
        self,
        db: Any,
        driver: str,
        root_dir: str | Path,
        *,
        system_dir: str | Path | None = None,
    ) -> None:
        configured_driver = driver.lower()
        self.driver = normalize_driver(configured_driver)
        if self.driver not in MIGRATION_DDL:
            available = ', '.join(sorted(MIGRATION_DDL))
            raise MigrationError(
                f"SQL migrations are not supported for '{configured_driver}'. "
                f'Supported drivers: {available}'
            )

        self.db = db
        self.root_dir = Path(root_dir)
        self.system_dir = Path(system_dir) if system_dir else Path(__file__).resolve().parent

    def run_pending(self) -> list[str]:
        """Apply pending migrations in built-in-then-project order."""
        self._ensure_table()
        applied = self._applied()
        newly_applied = []

        for source, path in self._discover():
            key = (source, path.name)
            checksum = self._checksum(path)
            stored_checksum = applied.get(key, {}).get('checksum') or ''
            if key in applied:
                if stored_checksum and stored_checksum != checksum:
                    raise MigrationError(
                        f"Migration '{source}:{path.name}' changed after it was applied. "
                        'Create a new migration instead of editing an applied file.'
                    )
                continue

            self._apply(source, path, checksum)
            newly_applied.append(f'{source}:{path.name}')

        return newly_applied

    def status(self) -> list[dict[str, Any]]:
        """Return applied and pending migrations without applying them."""
        self._ensure_table()
        applied = self._applied()
        result = []
        for source, path in self._discover():
            record = applied.get((source, path.name), {})
            checksum = self._checksum(path)
            result.append(
                {
                    'source': source,
                    'name': path.name,
                    'applied': bool(record),
                    'applied_at': record.get('applied_at'),
                    'checksum': checksum,
                    'changed': bool(record.get('checksum') and record['checksum'] != checksum),
                }
            )
        return result

    def _discover(self) -> list[tuple[str, Path]]:
        directories = (
            ('system', self.system_dir / self.driver),
            ('user', self.root_dir / 'migrations' / self.driver),
        )
        migrations = []
        for source, directory in directories:
            if not directory.is_dir():
                continue
            files = [
                path
                for path in directory.iterdir()
                if path.is_file() and _MIGRATION_FILENAME.fullmatch(path.name)
            ]
            files.sort(
                key=lambda path: (
                    int(_MIGRATION_FILENAME.fullmatch(path.name).group(1)),
                    path.name,
                )
            )
            migrations.extend((source, path) for path in files)
        return migrations

    def _ensure_table(self) -> None:
        ddl = MIGRATION_DDL[self.driver]
        if self.driver == 'oracle':
            cursor = self.db.cursor()
            try:
                cursor.execute(ddl)
            finally:
                cursor.close()
        else:
            self.db.execute(ddl)
        self.db.commit()

    def _applied(self) -> dict[tuple[str, str], dict[str, Any]]:
        rows = self.db.fetchall(
            f'SELECT migration_source, migration_name, applied_at, checksum '
            f'FROM homer_migrations WHERE driver = {self._ph(0)}',
            [self.driver],
            dictionary=True,
        )
        records = {}
        for row in rows:
            if isinstance(row, dict):
                source = row['migration_source']
                name = row['migration_name']
                applied_at = row['applied_at']
                checksum = row['checksum']
            else:
                source, name, applied_at, checksum = row
            records[(source, name)] = {
                'applied_at': applied_at,
                'checksum': checksum,
            }
        return records

    def _apply(self, source: str, path: Path, checksum: str) -> None:
        sql = path.read_text(encoding='utf-8')
        statements = split_sql(sql, self.driver)
        transactional = self.driver in _TRANSACTIONAL_DDL_DRIVERS

        try:
            if transactional:
                self.db.execute('BEGIN')
            for statement in statements:
                self.db.execute(statement)
                if not transactional:
                    self.db.commit()

            self.db.execute(
                'INSERT INTO homer_migrations '
                '(migration_source, driver, migration_name, applied_at, checksum) '
                f'VALUES ({self._ph(0)}, {self._ph(1)}, {self._ph(2)}, '
                f'{self._ph(3)}, {self._ph(4)})',
                [source, self.driver, path.name, datetime.now(), checksum],
            )
            self.db.commit()
        except Exception as exc:
            with suppress(Exception):
                self.db.rollback()
            raise MigrationError(
                f"Failed to apply {source} migration '{path.name}': {exc}"
            ) from exc

    def _ph(self, index: int) -> str:
        style = getattr(self.db, '_placeholder_style', '%s')
        if style == ':name':
            return f':{index + 1}'
        if style == '?':
            return '?'
        return '%s'

    @staticmethod
    def _checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
