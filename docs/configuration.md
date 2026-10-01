# Конфигурация

Все настройки — в `config.yml` в корне проекта.

Смотрите [`config.example.yml`](../config.example.yml) как отправную точку.

## Разделы

### `app` — общее

```yaml
app:
  name: Homer
  version: 1.0.0
```

### ```logging``` — логирование

```yaml
logging:
  level: INFO          # DEBUG | INFO | WARNING | ERROR | CRITICAL
  console: true        # дублировать в stdout
```

Логи пишутся в ```var/logs/<команда>_YYYY-MM-DD.log```.

### ```databases``` — подключения к БД

```yaml
databases:
  postgres:
    host: localhost
    port: 5432
    database: mydb
    user: postgres
    password: secret
  oracle:
    host: localhost
    port: 1521
    service: ORCL
    user: cmdb
    password: secret
```

### ```mailer``` — отправка email

```yaml
mailer:
  transport: mailx        # smtp | mailx | sendmail | file
  templates_dir: email
  from: noreply@example.com
  from_name: Homer

  smtp:
    host: smtp.example.com
    port: 587
    user: user
    password: pass
    use_tls: true

  mailx:
    binary: /usr/bin/mailx
    from_arg: "-r"

  file:
    dir: var/mail         # для отладки
```

### ```scheduler``` — планировщик и очередь

```yaml
scheduler:
  storage: sqlite          # sqlite | postgres | oracle
  interval: 30
  lease_seconds: 300
  heartbeat_interval: 30
  max_workers: 4
  execution_mode: threads  # threads | processes | subprocess
  job_timeout_sec: 3600
  cancel_children_on_fail: true

  queue_defaults:
    max_attempts: 3
    retry_delay: 60

  sqlite:
    path: var/scheduler.db
```

### ```notifications``` — куда слать уведомления

```yaml
notifications:
  enabled: [log, telegram, mattermost]

  log:
    on: [failed, timeout, canceled]
    level: warning

  telegram:
    on: [failed, timeout, canceled]
    bot_token: "123:ABC"
    chat_ids: [123456789]

  mattermost:
    on: [failed, timeout, canceled]
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    channel: "town-square"
```

### Использование в коде

```pycon
config = context['config']

# Простой ключ
name = config.get('app.name')

# Вложенный — точечная нотация
host = config.get('databases.postgres.host')

# Со значением по умолчанию
level = config.get('logging.level', 'INFO')

# Вся конфигурация
all_config = config.all()
```

## Переменные окружения

Конфиг — обычный YAML. Можно комбинировать с переменными окружения в ваших командах:

```pycon
import os
token = os.environ.get('TELEGRAM_BOT_TOKEN') or config.get('notifications.telegram.bot_token')
```

## Загрузка альтернативного конфига

```bash
HOMER_CONFIG=/etc/homer/config.yml ./homer schedule:run
```

(Реализуется в вашем ```homer``` или через символическую ссылку — файл читается по фиксированному пути в ```homer```.)
