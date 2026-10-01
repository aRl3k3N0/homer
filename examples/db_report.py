"""
db-report — пример работы с БД и красивым выводом.
"""
from lib.db import connect
from lib.console import console, Color

DESCRIPTION = "Отчёт по пользователям из PostgreSQL"


def execute(context):
    config = context['config']
    logger = context['logger']
    command = context['command_name']

    limit = int(context['args'].get('limit', 20))

    with connect('postgres', config, prefix='databases.postgres') as db:
        rows = db.fetchall(
            "SELECT id, name, active, created_at "
            "FROM users ORDER BY id LIMIT %s",
            [limit],
            dictionary=True,
        )

    logger.info(f"Получено {len(rows)} записей", command=command)

    console.banner("Отчёт по пользователям", f"limit={limit}")
    console.table(
        headers=['ID', 'Имя', 'Активен', 'Создан'],
        rows=[
            [
                r['id'],
                r['name'],
                console.colored('да', Color.BRIGHT_GREEN) if r['active']
                    else console.colored('нет', Color.BRIGHT_RED),
                str(r['created_at'])[:10] if r['created_at'] else '—',
            ]
            for r in rows
        ],
        align=['r', 'l', 'c', 'l'],
    )
    return 0