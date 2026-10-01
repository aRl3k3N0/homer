"""
report:monthly — месячный отчёт с вложением.
"""
from datetime import datetime, timedelta
from pathlib import Path

from lib.db import connect
from lib.mailer import Mailer
from lib.console import console

DESCRIPTION = "Месячный отчёт"


def execute(context):
    config = context['config']
    args = context['args']
    root_dir = context['root_dir']
    command = context['command_name']

    period = args.get('period') or datetime.now().strftime('%Y-%m')
    to = args.get('to') or config.get('notifications.email.to', [])

    with connect('postgres', config, prefix='databases.postgres') as db:
        rows = db.fetchall(
            "SELECT kind, count(*) AS cnt FROM events "
            "WHERE to_char(created_at, 'YYYY-MM') = %s "
            "GROUP BY kind ORDER BY cnt DESC",
            [period],
            dictionary=True,
        )

    # Сформировать простой CSV
    out_dir = root_dir / 'var' / 'reports'
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"monthly-{period}.csv"
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('kind,count\n')
        for r in rows:
            f.write(f"{r['kind']},{r['cnt']}\n")

    console.table(
        headers=['Тип', 'Количество'],
        rows=[[r['kind'], r['cnt']] for r in rows],
        align=['l', 'r'],
    )

    if to:
        mailer = Mailer(config, root_dir / 'email')
        mailer.send(
            to=to,
            template_name='report',
            subject=f"Месячный отчёт {period}",
            context={'period': period, 'rows': rows, 'total': sum(r['cnt'] for r in rows)},
            attachments=[csv_path],
        )
        console.success(f"Отчёт отправлен на {to}")

    return 0