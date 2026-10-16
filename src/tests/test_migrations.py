from pathlib import Path

import pytest

from homer.commands import BUILTIN_COMMANDS, plugin as plugin_command
from homer.commands.make_migration import execute as make_migration
from homer.commands.migrate import execute as migrate
from homer.db import connect
from homer.migrations import MigrationError, MigrationRunner, split_sql


class DictConfig:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        value = self.values
        for part in key.split('.'):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


@pytest.fixture
def migration_db(tmp_path):
    db = connect('sqlite', {'path': str(tmp_path / 'migrations.sqlite')})
    yield db
    db.close()


def write_migration(directory: Path, name: str, sql: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(sql, encoding='utf-8')
    return path


def test_split_sql_keeps_quoted_semicolons_and_comments():
    statements = split_sql(
        """
        -- this ; is a comment
        CREATE TABLE records (value TEXT);
        INSERT INTO records VALUES ('semi;colon -- text');
        /* another ; comment */
        INSERT INTO records VALUES ("double;quoted");
        """,
        'sqlite',
    )

    assert len(statements) == 3
    assert "'semi;colon -- text'" in statements[1]
    assert '"double;quoted"' in statements[2]


def test_split_sql_supports_postgres_dollar_quotes_and_oracle_blocks():
    postgres = split_sql(
        "DO $$ BEGIN RAISE NOTICE 'inside;block'; END $$; SELECT 1;",
        'postgres',
    )
    oracle = split_sql(
        "BEGIN\n  NULL;\n  NULL;\nEND;\n/\nCREATE TABLE t (id NUMBER);",
        'oracle',
    )

    assert len(postgres) == 2
    assert len(oracle) == 2
    assert 'NULL;' in oracle[0]
    assert oracle[1] == 'CREATE TABLE t (id NUMBER)'


def test_runner_applies_system_then_project_migrations_once(migration_db, tmp_path):
    system_dir = tmp_path / 'builtins'
    project_dir = tmp_path / 'project'
    write_migration(
        system_dir / 'sqlite',
        '001_create_table.sql',
        'CREATE TABLE records (value TEXT);',
    )
    write_migration(
        project_dir / 'migrations' / 'sqlite',
        '001_seed_data.sql',
        "INSERT INTO records VALUES ('project;data');",
    )
    runner = MigrationRunner(
        migration_db,
        'sqlite',
        project_dir,
        system_dir=system_dir,
    )

    assert runner.run_pending() == [
        'system:001_create_table.sql',
        'user:001_seed_data.sql',
    ]
    assert runner.run_pending() == []
    assert migration_db.fetchall('SELECT value FROM records')[0][0] == 'project;data'
    assert all(row['applied'] for row in runner.status())


def test_runner_rejects_edits_to_applied_migrations(migration_db, tmp_path):
    system_dir = tmp_path / 'builtins'
    migration = write_migration(
        system_dir / 'sqlite',
        '001_create_table.sql',
        'CREATE TABLE records (value TEXT);',
    )
    runner = MigrationRunner(
        migration_db,
        'sqlite',
        tmp_path / 'project',
        system_dir=system_dir,
    )
    runner.run_pending()
    migration.write_text('CREATE TABLE records (value INTEGER);', encoding='utf-8')

    with pytest.raises(MigrationError, match='changed after it was applied'):
        runner.run_pending()


def test_failed_migration_rolls_back_and_is_not_recorded(migration_db, tmp_path):
    system_dir = tmp_path / 'builtins'
    migration = write_migration(
        system_dir / 'sqlite',
        '001_broken.sql',
        'CREATE TABLE partial_table (id INTEGER); INSERT INTO missing_table VALUES (1);',
    )
    runner = MigrationRunner(
        migration_db,
        'sqlite',
        tmp_path / 'project',
        system_dir=system_dir,
    )

    with pytest.raises(MigrationError, match='Failed to apply'):
        runner.run_pending()

    assert (
        migration_db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='partial_table'"
        )
        is None
    )
    assert migration_db.fetchone('SELECT migration_name FROM homer_migrations') is None

    migration.write_text(
        'CREATE TABLE partial_table (id INTEGER);',
        encoding='utf-8',
    )
    assert runner.run_pending() == ['system:001_broken.sql']


def test_make_migration_supports_project_and_plugin_scopes(tmp_path):
    (tmp_path / 'plugins' / 'sample').mkdir(parents=True)
    config = DictConfig({'scheduler': {'storage': 'sqlite'}})
    project_context = {
        'args': {'name': 'create records', 'template': 'create_table', 'table': 'records'},
        'root_dir': str(tmp_path),
        'config': config,
    }

    assert make_migration(project_context) == 0
    project_file = tmp_path / 'migrations' / 'sqlite' / '001_create_records.sql'
    assert project_file.is_file()
    assert 'CREATE TABLE records (' in project_file.read_text(encoding='utf-8')

    plugin_context = {
        'args': {'plugin': 'sample', 'name': 'add records'},
        'root_dir': str(tmp_path),
        'config': config,
    }
    assert make_migration(plugin_context) == 0
    plugin_file = tmp_path / 'plugins' / 'sample' / 'migrations' / 'sqlite' / '001_add_records.sql'
    assert plugin_file.is_file()
    assert '-- Scope:     plugin:sample' in plugin_file.read_text(encoding='utf-8')


def test_migrate_command_is_registered_and_applies_project_migrations(tmp_path):
    db_path = tmp_path / 'app.sqlite'
    write_migration(
        tmp_path / 'migrations' / 'sqlite',
        '001_create_records.sql',
        'CREATE TABLE records (id INTEGER PRIMARY KEY);',
    )
    context = {
        'args': {},
        'root_dir': str(tmp_path),
        'config': DictConfig(
            {
                'scheduler': {
                    'storage': 'sqlite',
                    'sqlite': {'path': str(db_path)},
                },
            }
        ),
    }

    assert 'migrate' in BUILTIN_COMMANDS
    assert migrate(context) == 0

    db = connect('sqlite', {'path': str(db_path)})
    try:
        assert (
            db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='records'")
            is not None
        )
    finally:
        db.close()


def test_project_migrate_returns_nonzero_when_plugin_migrations_fail(monkeypatch):
    class FailingManager:
        def discover(self, *args, **kwargs):
            pass

        def load_all(self, *args, **kwargs):
            pass

        def run_migrations(self, *args, **kwargs):
            return {
                'applied': [],
                'skipped': [],
                'errors': [('broken-plugin', 'migration failed')],
            }

    class StubDB:
        closed = False

        def close(self):
            self.closed = True

    manager = FailingManager()
    db = StubDB()
    monkeypatch.setattr(
        plugin_command,
        '_get_manager_and_config',
        lambda context: (manager, {}, db, 'sqlite'),
    )

    result = plugin_command.migrate(
        {
            'args': {},
            'root_dir': '.',
        }
    )

    assert result == 1
    assert db.closed
