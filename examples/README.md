# Примеры команд

Готовые примеры для копирования в ваш проект.

## Список

- [hello.py](hello.py) — минимальная команда.
- [db_report.py](db_report.py) — отчёт из Postgres с таблицей в консоли.
- [send_email.py](send_email.py) — отправка письма.
- [send_telegram.py](send_telegram.py) — уведомление в Telegram.
- [chained_commands.py](chained_commands.py) — вызов других команд через очередь.
- [deploy/main.py](deploy/main.py) — оркестрация деплоя.
- [report/daily.py](report/daily.py) — ежедневный отчёт.
- [report/monthly.py](report/monthly.py) — месячный отчёт.

## Как использовать

Скопируйте нужный файл в `commands/`:

```bash
cp examples/hello.py commands/
cp -r examples/report commands/
```

Затем:

```bash
homer hello --name=Иван
homer hello --name=Иван --shout
homer report:daily --period=2026-09 --to=ops@example.com
```

