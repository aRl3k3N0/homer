"""
deploy — оркестрация деплоя через очередь Homer.
"""
from lib.console import console, Color

DESCRIPTION = "Собрать релиз и раскатать на серверы"


def execute(context):
    queue = context['queue']
    logger = context['logger']
    args = context['args']

    env = args.get('env', 'dev')
    hosts = (args.get('hosts') or 'srv1,srv2,srv3').split(',')

    console.section(f"Деплой в {env}")

    # Шаг 1: собрать
    console.info(f"Сборка релиза (env={env})...")
    try:
        r = queue.call('build:release', env=env, timeout=900, priority=100)
    except Exception as e:
        console.error(f"Сборка упала: {e}")
        return 1
    if not r.ok:
        console.error(f"Сборка вернула ошибку: {r.error}")
        return 1

    # Шаг 2: раскатать на все хосты параллельно
    for host in hosts:
        job_id = queue.push('deploy:host', host=host, env=env, priority=90)
        console.list_item(host, f"job #{job_id}")

    console.success(f"Собрано, деплой запущен на {len(hosts)} серверах")
    logger.info(f"deploy: env={env}, hosts={hosts}", command='deploy')
    return 0