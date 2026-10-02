"""
Миграции плагинов.

Таблица учёта:
    homer_plugin_migrations(
        plugin_name, driver, migration_name, applied_at, checksum
    )

- Порядок: сортировка по номеру в имени файла.
- Применяется один раз; повторный запуск — no-op.
- checksum позволяет предупредить, что файл миграции изменили после применения.
- Транзакция: SQLite/Postgres поддерживают откат DDL; Oracle/MySQL могут
  фиксировать DDL независимо от явного rollback.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re

from .plugin import PluginInfo

DDL_MIGRATIONS = {
    'sqlite': """
        CREATE TABLE IF NOT EXISTS homer_plugin_migrations (
            plugin_name    TEXT NOT NULL,
            driver         TEXT NOT NULL,
            migration_name TEXT NOT NULL,
            applied_at     TEXT NOT NULL,
            checksum       TEXT,
            PRIMARY KEY (plugin_name, driver, migration_name)
        );
    """,
    'postgres': """
        CREATE TABLE IF NOT EXISTS homer_plugin_migrations (
            plugin_name    VARCHAR(255) NOT NULL,
            driver         VARCHAR(64) NOT NULL,
            migration_name VARCHAR(255) NOT NULL,
            applied_at     TIMESTAMP NOT NULL,
            checksum       VARCHAR(64),
            PRIMARY KEY (plugin_name, driver, migration_name)
        );
    """,
    'oracle': """
        BEGIN
            EXECUTE IMMEDIATE '
                CREATE TABLE homer_plugin_migrations (
                    plugin_name    VARCHAR2(255) NOT NULL,
                    driver         VARCHAR2(64) NOT NULL,
                    migration_name VARCHAR2(255) NOT NULL,
                    applied_at     TIMESTAMP NOT NULL,
                    checksum       VARCHAR2(64),
                    CONSTRAINT pk_homer_plugin_migrations
                        PRIMARY KEY (plugin_name, driver, migration_name)
                )';
        EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
        END;
    """,
    'mysql': """
        CREATE TABLE IF NOT EXISTS homer_plugin_migrations (
            plugin_name    VARCHAR(255) NOT NULL,
            driver         VARCHAR(64) NOT NULL,
            migration_name VARCHAR(255) NOT NULL,
            applied_at     DATETIME NOT NULL,
            checksum       VARCHAR(64),
            PRIMARY KEY (plugin_name, driver, migration_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
}
DDL_MIGRATIONS['postgresql'] = DDL_MIGRATIONS['postgres']
DDL_MIGRATIONS['mariadb'] = DDL_MIGRATIONS['mysql']


class MigrationRunner:
    def __init__(self, plugin: PluginInfo, driver: str, db):
        self.plugin = plugin
        self.driver = driver
        self.db = db
        self.dir = plugin.migrations_for(driver)

    # ─────────── Public ───────────

    def up(self) -> list[str]:
        """Прогоняет ещё не применённые миграции. Возвращает список имён."""
        if not self.dir:
            return []
        self._ensure_table()

        applied = self._applied_names()
        files = self._discover_files()

        newly_applied = []
        for f in files:
            name = f.name
            if name in applied:
                # Проверяем checksum
                stored = applied[name]
                current = self._checksum(f)
                if stored and stored != current:
                    raise RuntimeError(
                        f"Миграция '{name}' плагина '{self.plugin.name}' "
                        f"была изменена после применения "
                        f"(checksum {stored[:8]} → {current[:8]}). "
                        f"Создайте новую миграцию вместо правки старой."
                    )
                continue

            self._apply(f)
            newly_applied.append(f"{self.plugin.name}:{name}")

        return newly_applied

    def down_all(self) -> bool:
        """Выполняет uninstall.sql плагина для этого драйвера."""
        if not self.dir:
            return False
        uninstall = self.dir / 'uninstall.sql'
        if not uninstall.exists():
            return False

        text = uninstall.read_text(encoding='utf-8')
        for stmt in _split_sql(text, self.driver):
            self.db.execute(stmt)
        self.db.commit()

        # Удаляем записи о применённых миграциях
        self.db.execute(
            f"DELETE FROM homer_plugin_migrations "
            f"WHERE plugin_name = {self._ph(0)} AND driver = {self._ph(1)}",
            [self.plugin.name, self.driver],
        )
        self.db.commit()
        return True

    def status(self) -> list[dict]:
        """Состояние всех миграций плагина."""
        self._ensure_table()
        applied = self._applied_names()
        files = self._discover_files()
        result = []
        for f in files:
            name = f.name
            result.append(
                {
                    'name': name,
                    'applied': name in applied,
                    'applied_at': None,
                    'checksum': self._checksum(f),
                }
            )
        return result

    # ─────────── Внутреннее ───────────

    def _discover_files(self) -> list[Path]:
        if not self.dir:
            return []
        files = []
        for f in self.dir.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() != '.sql':
                continue
            if f.name == 'uninstall.sql':
                continue
            # Ожидаем <num>_<desc>.sql
            if not re.match(r'^\d+', f.name):
                continue
            files.append(f)
        files.sort(key=lambda p: _numeric_prefix(p.name))
        return files

    def _apply(self, path: Path):
        sql = path.read_text(encoding='utf-8')
        checksum = self._checksum(path)
        statements = _split_sql(sql, self.driver)

        # Oracle и MySQL фиксируют многие DDL-команды независимо от транзакции.
        use_tx = self.driver in ('sqlite', 'postgres', 'postgresql')

        try:
            if use_tx:
                self.db.execute('BEGIN')
                for stmt in statements:
                    self.db.execute(stmt)
                self._mark_applied(path.name, checksum)
                self.db.commit()
            else:
                for stmt in statements:
                    self.db.execute(stmt)
                    self.db.commit()
                self._mark_applied(path.name, checksum)
                self.db.commit()
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass
            raise

    def _ensure_table(self):
        ddl = DDL_MIGRATIONS.get(self.driver)
        if not ddl:
            raise RuntimeError(
                f"Не поддерживается драйвер '{self.driver}' для миграций. "
                f"Доступные: {', '.join(DDL_MIGRATIONS)}"
            )
        if self.driver == 'oracle':
            cur = self.db.cursor()
            try:
                cur.execute(ddl)
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
        else:
            for stmt in [s.strip() for s in ddl.split(';') if s.strip()]:
                self.db.execute(stmt)
        self.db.commit()

    def _applied_names(self) -> dict[str, str]:
        rows = self.db.fetchall(
            f"SELECT migration_name, checksum "
            f"FROM homer_plugin_migrations "
            f"WHERE plugin_name = {self._ph(0)} AND driver = {self._ph(1)}",
            [self.plugin.name, self.driver],
            dictionary=True,
        )
        return {
            (r['migration_name'] if isinstance(r, dict) else r[0]): (
                r['checksum'] if isinstance(r, dict) else r[1]
            )
            or ''
            for r in rows
        }

    def _mark_applied(self, name: str, checksum: str):
        self.db.execute(
            f"INSERT INTO homer_plugin_migrations "
            f"(plugin_name, driver, migration_name, applied_at, checksum) "
            f"VALUES ({self._ph(0)}, {self._ph(1)}, {self._ph(2)}, "
            f"{self._ph(3)}, {self._ph(4)})",
            [self.plugin.name, self.driver, name, datetime.now(), checksum],
        )

    def _ph(self, idx: int) -> str:
        style = getattr(self.db, '_placeholder_style', '%s')
        if style == ':name':
            return f':{idx + 1}'
        if style == '?':
            return '?'
        return '%s'

    @staticmethod
    def _checksum(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()


def _numeric_prefix(name: str) -> int:
    m = re.match(r'^(\d+)', name)
    return int(m.group(1)) if m else 0


def _split_sql(text: str, driver: str) -> list[str]:
    """См. lib/plugins/manager._split_sql — вынесем в общий модуль."""
    from .manager import _split_sql as _split

    return _split(text, driver)
