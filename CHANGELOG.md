# Changelog

Все значимые изменения проекта фиксируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### В планах
- Web-UI для просмотра очереди.
- Плагины нотификаторов из внешних пакетов.
- Асинхронные воркеры (asyncio).
- Метрики Prometheus.
- Поддержка Rocket.Chat, Discord, Microsoft Teams.

## [1.0.0] — 2026-09-19

### Добавлено
- Ядро Homer: загрузка команд из `commands/`, разбор аргументов
  (`--key=value`, флаги, позиционные).
- Конфигурация `config.yml` с точечной нотацией (`config.get('app.name')`).
- Логирование с разделением по дням и командам (`logs/<command>_<date>.log`).
- Красивый вывод: цвета, таблицы, прогресс-бары, баннеры, панели.
- Драйверы БД: `OracleDB`, `PostgresDB`, `SQLiteDB`, базовый `BaseDB`
  и `ConnectionConfig` для универсального подключения.
- Mailer: транспорты `smtp`, `mailx`, `sendmail`, `file`; Jinja2-шаблоны,
  вложения, cc/bcc, reply-to.
- Планировщик cron (5 полей) с распределённым запуском
  (атомарный `acquire_task`, lease, heartbeat).
- Очередь задач: `push`, `later`, `call` (sync), статусы, приоритеты.
- Retry: `attempts`, `max_attempts`, `retry_delay`,
  инкремент `attempts` в `acquire_next`.
- Каскадная отмена дочерних job-ов.
- Hard-kill через `subprocess` с `timeout_sec` для конкретного job-а.
- Режимы воркеров: `threads`, `processes` (`ProcessPoolExecutor`),
  `subprocess` (изоляция + kill).
- Нотификаторы: email, telegram, slack, mattermost, file, log, desktop.
- Встроенные команды: `shell`, `make:command`, `mail:check`,
  `schedule:*`, `queue:*`, `notify:test`.
- REPL `homer shell` с Python-режимом и специальными командами `:`.
- Генератор команд `make:command` с шаблоном.
- Полная документация в `docs/` и примеры в `examples/`.
- Набор юнит-тестов на pytest (`tests/`).
- Makefile, CI (GitHub Actions), конфигурация ruff/flake8/mypy.
- Автогенерация API-документации через Sphinx (`docs/api-generated/`).

[Unreleased]: https://example.com/homer/compare/v1.0.0...HEAD
[1.0.0]: https://example.com/homer/releases/tag/v1.0.0
