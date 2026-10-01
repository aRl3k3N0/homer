"""
report:daily — ежедневный отчёт с отправкой письма.
"""
from datetime import date, timedelta
from lib.db import connect
from lib.mailer import Mailer
from lib.console import console

DESCRIPTION = "Ежедневный отчёт"


def execute(context):
    config = context['config']
    logger = context['logger']
    args = context['args']
    command = context['command_name']

    period = args.get('period') or str(date.today() - timedelta(days=1))
    to = args.get('to') or config.get('notifications.email.to', [])

    logger.info(f"Отчёт за {period} → {to}", command=command)

    with connect('postgres', config, prefix='databases.postgres') as db:
        total = db.fetchval("SELECT count(*) FROM events WHERE day = %s", [period]) or 0
        errors = db.fetchval(
            "SELECT count(*) FROM events WHERE day = %s AND status = 'error'",
            [period],
        ) or 0

    console.section("Сводка")
    console.key_value('Период', period)
    console.key_value('Всего', total)
    console.key_value('Ошибок', errors)

    if not to:
        console.warning("Получатели не заданы — письмо не отправлено")
        return 0

    mailer = Mailer(config, context['root_dir'] / 'email')
    mailer.send(
        to=to,
        template_name='notifications/job_ok',
        context={
            'job_id': 0,
            'command': command,
            'args': {'period': period},
            'args_pretty': f"period={period}",
            'status': 'done',
            'exit_code': 0,
            'error': '',
            'result': f"total={total}, errors={errors}",
            'duration': None,
            'triggered_by': 'report:daily',
            'attempts': 1,
            'max_attempts': 1,
            'started_at': None,
            'finished_at': None,
            'ok': True,
        },
    )
    console.success(f"Письмо отправлено на {to}")
    return 0