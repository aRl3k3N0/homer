# Homer — документация

**Homer** — консольный фреймворк для Python в стиле Laravel Artisan.

## Содержание

### Основы
- [Установка](installation.md)
- [Начало работы](getting-started.md)
- [Конфигурация](configuration.md)

### Команды
- [Обзор команд](commands.md)
- [Создание команд](creating-commands.md)
- [Аргументы командной строки](arguments.md)
- [Встроенные команды](builtin-commands.md)

### API
- [Config](config-api.md) — работа с `config.yml`
- [Logger](logger-api.md) — логирование по дням и командам
- [Console](console.md) — цвета, таблицы, прогресс-бары
- [DB](db-api.md) — Oracle / Postgres / SQLite + свои драйверы
- [Mailer](mailer-api.md) — отправка писем по шаблонам
- [Notify](notify-api.md) — email, telegram, slack, mattermost, file, log, desktop
- [Queue](queue-api.md) — очередь задач, retry, отмена
- [Scheduler](scheduler-api.md) — cron, распределённый запуск

### Практика
- [Отправка уведомлений из команды](notifications-from-commands.md)
- [Shell / REPL](shell.md)
- [Развёртывание](deployment.md)
- [Тестирование](testing.md)
- [FAQ](faq.md)

### Примеры
- [Готовые примеры команд](../examples/README.md)

## Лицензия

MIT.