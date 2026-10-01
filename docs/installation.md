# Установка

## Требования

- Python 3.9+
- pip

## Шаги

```bash
git clone <repo> homer && cd homer

# Основные зависимости
pip install -r requirements.txt

# Опциональные драйверы БД:
pip install cx_Oracle              # Oracle
pip install psycopg2-binary        # PostgreSQL (уже в requirements.txt)
# SQLite — встроен в Python

# Jinja2 — для шаблонов писем с условиями/циклами
pip install Jinja2

# requests — для telegram/slack/mattermost (fallback на urllib, если нет)

chmod +x homer
./homer
```

## Проверка
```bash
./homer mail:check       # проверить настройки mailer
./homer queue:status     # статус очереди
./homer schedule:list    # список cron-задач
```

## Обновление
```bash
git pull
pip install -r requirements.txt
```

## Зависимости

Файл ```requirements.txt```:

* ```PyYAML``` — парсинг ```config.yml```
* ```psycopg2-binary``` — PostgreSQL
* ```cx_Oracle``` — Oracle
* ```Jinja2``` — шаблоны писем
* ```requests``` — HTTP-запросы (Telegram/Slack/Mattermost)

Если какой-то драйвер не нужен — уберите его из ```requirements.txt```.
