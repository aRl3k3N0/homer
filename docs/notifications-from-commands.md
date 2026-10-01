# Отправка уведомлений из команды

Иногда нужно отправить уведомление **не по завершении job-а**, а прямо из тела команды —
например, промежуточный статус, персональное сообщение пользователю, alert по критичной ошибке.

Есть два пути:

1. **Через `NotifyManager`** — если хотите использовать уже настроенные каналы (email, telegram, slack, mattermost, log, file, desktop).
2. **Напрямую** — если нужен специфичный формат (например, письмо по своему шаблону, конкретный webhook).

## Вариант 1: через NotifyManager (рекомендуется)

```pycon
from datetime import datetime
from lib.notify import NotifyManager
from lib.notify.base import NotifyEvent


def execute(context):
    config = context['config']
    logger = context['logger']
    command = context['command_name']

    # Создаём менеджер (подхватит все активные нотификаторы из config.yml)
    notify = NotifyManager(config, logger=logger, root_dir=context['root_dir'])

    # Формируем событие
    event = NotifyEvent(
        job_id=0,                                 # 0 — «не из job-а»
        command=command,
        args=context['args'],
        status='failed',                          # 'done' | 'failed' | 'canceled' | 'timeout'
        exit_code=1,
        error='БД недоступна',
        result=None,
        duration_sec=None,
        triggered_by='cli',
        attempts=1,
        max_attempts=1,
        started_at=datetime.now(),
        finished_at=datetime.now(),
    )

    # Разослать по всем активным каналам
    notify.emit(event)
    return 1
```

Кому уйдёт: всем нотификаторам, где ```event.status``` попадает в их ```on=[...]```.
Например, при ```on: [failed, timeout, canceled]``` в telegram и mattermost — уведомление уйдёт туда.

### Как отправить «успех» откуда-то

Если хотите уведомить об успешном завершении команды, но ```done``` не входит в ```on``` у ваших нотификаторов — просто добавьте ```done``` в список:

### Как отправить только в один канал

```NotifyManager``` не умеет «только telegram». Используйте нотификатор напрямую:

```pycon
from lib.notify.telegram_notifier import TelegramNotifier

notifier = TelegramNotifier(config)
notifier.send(event)
```

### Своё событие с произвольным текстом

Хотите не «Job #0 ... failed», а свои слова — сделайте свой лёгкий нотификатор или используйте ```TelegramNotifier```/```MattermostNotifier```/```SlackNotifier``` c готовым payload:

```pycon
from lib.notify.telegram_notifier import TelegramNotifier

class CustomTelegram(TelegramNotifier):
    def _format(self, event):
        return f"⚠️ <b>Важное</b>\n{event.command} упала: {event.error}"

notifier = CustomTelegram(config)
notifier.on = ['failed']              # для явного send() фильтр не нужен,
                                      # т.к. вы вызываете .send() напрямую
notifier.send(event)
```

## Вариант 2: напрямую — email

```pycon
from lib.mailer import Mailer

def execute(context):
    mailer = Mailer(context['config'], context['root_dir'] / 'email')
    mailer.send(
        to='ops@example.com',
        template_name='welcome',
        context={'user': context['args'].get('user', 'anonymous')},
    )
    return 0
```

## Вариант 2: напрямую — Telegram

```pycon
from lib.notify.base import NotifyEvent
from lib.notify.telegram_notifier import TelegramNotifier
from datetime import datetime

def execute(context):
    notifier = TelegramNotifier(context['config'])
    event = NotifyEvent(
        job_id=0, command=context['command_name'], args=context['args'],
        status='failed', exit_code=1, error='manual notify',
        result=None, duration_sec=None, triggered_by='cli',
        attempts=1, max_attempts=1,
        started_at=datetime.now(), finished_at=datetime.now(),
    )
    notifier.send(event)
    return 0
```

## Вариант 2: напрямую — Mattermost

```pycon
from lib.notify.mattermost_notifier import MattermostNotifier
from lib.notify.base import NotifyEvent
from datetime import datetime

def execute(context):
    n = MattermostNotifier(context['config'])
    # Временно разрешаем done, если хотим отправлять успех
    n.on = ['done', 'failed']

    event = NotifyEvent(...)  # как выше
    n.send(event)
    return 0
```

## Вариант 2: напрямую — Slack

```pycon
from lib.notify.slack_notifier import SlackNotifier
from lib.notify.base import NotifyEvent

def execute(context):
    SlackNotifier(context['config']).send(NotifyEvent(...))
    return 0
```

## Как выбирать канал динамически

Пусть команда принимает ```--channel=telegram,mattermost```:

```pycon
from lib.notify import REGISTRY

def execute(context):
    channels = (context['args'].get('channel') or 'log').split(',')
    event = NotifyEvent(...)
    for name in channels:
        cls = REGISTRY.get(name.strip())
        if not cls:
            context['logger'].warning(f"Нет нотификатора '{name}'")
            continue
        # log требует logger, email требует root_dir — упрощённо
        try:
            cls(context['config']).send(event)
        except TypeError:
            cls(context['config'], context['logger']).send(event)
    return 0
```

## Что попадёт в уведомление

* **job_id**, **command**, **args** — что выполнялось.
* **status** — ```done``` / ```failed``` / ```canceled``` / ```timeout```.
* **exit_code**, **attempts** / **max_attempts**.
* **error** — текст ошибки (обычно с трейсбеком).
* **result** — собранный stdout команды (если выполнялась через воркер).
* **duration_sec**, **started_at**, **finished_at**.
* **triggered_by** — источник (```cron:name```, ```cli```, ```job#N```, ```shell:cmd```).

## Полезные советы

* Не отправляйте уведомления **на каждый вызов** из CLI — забьёте канал. Оставьте нотификацию для cron/queue job-ов.
* Для критичных алертов используйте ```mention_on_fail: "@channel"``` в Mattermost / ```@here``` в Slack.
* Ограничьте частоту: например, «не чаще раза в час на одну и ту же ошибку» — реализуется поверх ```NotifyManager.emit``` своей обёрткой.
* Тяжёлые ошибки (трейсбек 100 КБ) обрезаются до ~1500 символов в Telegram/Mattermost/Slack. Для полного текста используйте email с шаблоном.
