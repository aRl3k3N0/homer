# API: Notify

Модуль `lib.notify` — уведомления о завершении задач планировщика/очереди
в email, telegram, slack, mattermost, файл, лог, desktop.

## Как работает

1. `NotifyManager` создаётся в `Scheduler` из `config.yml → notifications.enabled`.
2. После завершения job-а `Scheduler._finalize_job` вызывает `notify_manager.emit_from_job(job)`.
3. Менеджер шлёт событие всем включённым нотификаторам.

## Событие

```pycon
from lib.notify.base import NotifyEvent

event = NotifyEvent(
    job_id=42,
    command='cmdb:update',
    args={'user': 'cmdb', 'ver': 16},
    status='failed',            # 'done' | 'failed' | 'canceled' | 'timeout'
    exit_code=1,
    error='Something went wrong',
    result=None,                # вывод команды (может быть None)
    duration_sec=12.34,
    triggered_by='cron:daily-cmdb',
    attempts=2,
    max_attempts=3,
    started_at=datetime.now(),
    finished_at=datetime.now(),
)
```

Свойства:

* ```event.ok``` — ```True```, если ```status == 'done'``` и ```exit_code in (None, 0)```.
* ```event.short_command``` — ```'cmdb:update (user=cmdb, ver=16)'```.

## Нотификаторы

| Имя              | Требует        | Куда шлёт               |
|------------------|----------------|-------------------------|
| ```log```        | —              | Лог Homer               |
| ```file```       | —              | JSONL-файл              |
| ```email```      | ```mailer```   | Email                   |
| ```telegram```   | ```requests``` | Telegram                |
| ```slack```      | ```requests``` | Slack                   |
| ```mattermost``` | ```requests``` | Mattermost              |
| ```desktop```    | —              | notify-send / osascript |

## Конфигурация

Смотри [configuration.md](configuration.md), секция ```notifications```.

## Проверка

```bash
homer notify:test --status=failed
homer notify:test --status=done
homer notify:test --status=timeout
```

## Использование из команды

См. гайд: [Отправка уведомлений из команды](notifications-from-commands.md).

## Кастомный нотификатор

```pycon
# lib/notify/my_notifier.py
from .base import BaseNotifier, NotifyEvent

class MyNotifier(BaseNotifier):
    name = 'my'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.my', {}) or {}
        self.on = cfg.get('on', ['failed'])

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        # TODO: своя логика
        ...
```

Регистрация в ```lib/notify/__init__.py```:

```pycon
from .my_notifier import MyNotifier
REGISTRY['my'] = MyNotifier
```

И в конфиге: ```notifications.enabled: [..., my]```.

## Обработка ошибок

```NotifyManager.emit``` ловит исключения каждого нотификатора отдельно: падение одного не блокирует остальные. Ошибки пишутся в лог с ```command='notify'```.
