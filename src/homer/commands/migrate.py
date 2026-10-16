"""Apply built-in and project database migrations."""

from pathlib import Path

from homer.core.console import console
from homer.db import connect
from homer.migrations import SUPPORTED_DRIVERS, MigrationRunner
from homer.migrations.sql import normalize_driver

DESCRIPTION = 'Применить миграции Homer и проекта'


def execute(context):
    args = context['args']
    config = context['config']
    root = Path(context['root_dir'])

    scheduler = config.get('scheduler', {}) or {}
    configured_driver = str(args.get('driver') or scheduler.get('storage') or 'sqlite').lower()

    if configured_driver not in SUPPORTED_DRIVERS:
        console.error(
            f"SQL-миграции не поддерживают драйвер '{configured_driver}'. "
            'Поддерживаются: sqlite, postgres, postgresql, oracle, mysql, mariadb'
        )
        return 1

    driver = normalize_driver(configured_driver)
    db_config = (
        scheduler.get(configured_driver)
        or scheduler.get(driver)
        or config.get(f'databases.{configured_driver}')
        or config.get(f'databases.{driver}')
    )
    if not db_config and driver == 'sqlite':
        db_config = {'path': 'var/scheduler.db'}

    db = None
    try:
        db = connect(configured_driver, db_config)
        runner = MigrationRunner(db, configured_driver, root)

        if args.get('status'):
            rows = runner.status()
            table_rows = []
            has_changed = False
            for row in rows:
                if row['changed']:
                    state = 'изменена после применения'
                    has_changed = True
                else:
                    state = 'применена' if row['applied'] else 'ожидает'
                table_rows.append([row['source'], row['name'], state])

            if table_rows:
                console.table(
                    headers=['Источник', 'Миграция', 'Состояние'],
                    rows=table_rows,
                    align=['l', 'l', 'l'],
                )
            else:
                console.comment('Файлы миграций не найдены')
            return 1 if has_changed else 0

        applied = runner.run_pending()
        if applied:
            for migration in applied:
                console.success(f'Применена: {migration}')
        else:
            console.comment('Нет новых миграций')
        return 0
    except Exception as exc:
        console.error(f'Ошибка миграции: {exc}')
        return 1
    finally:
        if db is not None:
            db.close()
