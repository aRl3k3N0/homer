"""
chain — вызов других команд: синхронно и асинхронно.
"""
DESCRIPTION = "Пример вызова других команд через очередь"


def execute(context):
    queue = context['queue']
    args = context['args']
    logger = context['logger']

    # 1) Синхронно: дождаться результата
    try:
        r = queue.call('hello', name='chain', timeout=30, priority=100)
        if r.ok:
            logger.info(f"hello вернул: {r.output!r}")
        else:
            logger.error(f"hello упал: {r.error}")
    except Exception as e:
        logger.error(f"Ошибка вызова: {e}")

    # 2) Асинхронно: 3 задачи параллельно
    for name in ('a', 'b', 'c'):
        job_id = queue.push('hello', name=name, priority=5)
        print(f"→ hello name={name}: job #{job_id}")

    # 3) Отложенно: через 5 минут
    queue.later('hello', minutes=5, name='later')

    return 0