"""
fetch-all — демонстрация прогресс-бара с промежуточным выводом.
"""
import time
import random

from lib.console import console

DESCRIPTION = "Демонстрация sticky-прогресс-бара"


def execute(context):
    logger = context['logger']
    command = context['command_name']
    args = context['args']

    count = int(args.get('count', 50))
    fail_at = args.get('fail-at')
    fail_at = int(fail_at) if fail_at else None

    console.section(f"Обработка {count} элементов")

    items = list(range(count))
    errors = 0

    with console.progress_ctx(
        total=len(items),
        prefix='Загрузка',
        show_eta=True,
        color=console._c.__self__ and None or None,  # дефолт
    ) as bar:
        for i, item in enumerate(items):
            time.sleep(random.uniform(0.02, 0.08))

            if fail_at is not None and i == fail_at:
                errors += 1
                # Это сообщение появится НАД баром
                console.error(f"Ошибка на элементе {item} — пропускаем")
                logger.warning(f"item {item} failed", command=command)
                bar.update()
                continue

            if i and i % 10 == 0:
                # Прогресс-сообщения — над баром
                console.comment(f"  → обработано {i} из {count}")

            bar.set_description(suffix=f"[{item}]")
            bar.update()

    if errors:
        console.warning(f"Завершено с {errors} ошибк(ами)")
        return 1

    console.success("Все элементы обработаны")
    return 0
