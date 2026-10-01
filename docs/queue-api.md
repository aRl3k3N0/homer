# API: Queue

Модуль `lib.queue`. Очередь задач с retry, отменой, приоритетами,
выполняется воркерами планировщика.

## Компоненты

- `QueueStorage` — низкоуровневое хранилище (`push`, `acquire_next`, `finish`).
- `Dispatcher` — то, что доступно как `context['queue']`.
- `QueueJob` — модель задачи.
- `JobStatus` — строковые статусы.

## `Dispatcher` — вызов из команды

### Асинхронный push

```pycon
def execute(context):
    job_id = context['queue'].push(
        'report:send',
        to='ops@example.com',
        period='2026-09',
        priority=10,
        max_attempts=5,
        retry_delay=120,
        timeout_sec=600,
    )
    print(f"job #{job_id}")
    return 0
```

## Параметры:

* ```priority=0``` — больше значит важнее.
* ```max_attempts=3``` — общее число попыток.
* ```retry_delay=60``` — секунд между попытками.
* ```timeout_sec=None``` — ограничение времени для subprocess-режима.
* ```run_at=datetime``` — не выполнять раньше времени.

## Отложенный push

```pycon
context['queue'].later('report:send', minutes=5, to='ops@example.com')
context['queue'].later('report:send', hours=1)
context['queue'].later('report:send', seconds=30)
```

## Синхронный вызов

```pycon
result = context['queue'].call(
    'cmdb:update',
    user='cmdb', ver=16,
    timeout=300,
    priority=100,
    max_attempts=1,     # sync по умолчанию не ретраит
)
if not result.ok:
    print("Ошибка:", result.error)
    return 1
print(result.output)
```

Возвращает ```QueueResult(job_id, status, output, error, exit_code)```.

Свойство ```result.ok```.

## Другие методы

```pycon
context['queue'].get(job_id)
context['queue'].list(status='pending', limit=100)
context['queue'].stats()
context['queue'].cancel(job_id)
```

## ```QueueStorage``` — для CLI/утилит

```pycon
from lib.queue import QueueStorage, Dispatcher

storage = QueueStorage(config)
try:
    d = Dispatcher(storage, config=config, triggered_by='cli')
    d.push('hello', name='world')
finally:
    storage.close()
```

## Модель ```QueueJob```

Поля, полезные в командах:

* ```id```, ```command```, ```args```, ```priority```, ```status```
* ```result```, ```exit_code```, ```error```
* ```created_at```, ```started_at```, ```finished_at```, ```run_at```
* ```attempts```, ```max_attempts```, ```retry_delay```
* ```parent_job_id```, ```triggered_by```
* ```timeout_sec```
* ```cancel_requested```

## CLI

```bash
homer queue:push --command=cmdb:update --args=user=cmdb,ver=16 \
  --priority=10 --max-attempts=5 --retry-delay=120 --timeout=600

homer queue:push --command=report:daily --delay=600

homer queue:list
homer queue:list --status=failed
homer queue:status
homer queue:cancel --id=42
homer queue:retry --id=42
homer queue:purge --older=86400

homer queue:work --interval=2 --workers=4 --execution-mode=threads
```

## Retry
Логика в ```QueueStorage.finish```:

* ```attempts``` увеличивается в ```acquire_next``` (атомарно, на каждом захвате).
* При ```failed``` и ```attempts < max_attempts``` — job снова становится ```pending``` с ```run_at = now + retry_delay```.
* При ```failed``` и a```ttempts >= max_attempts``` — окончательный ```failed```.
* Ручной retry: ```homer queue:retry --id=N``` (сбрасывает attempts).

## Отмена

```pycon
context['queue'].cancel(job_id)   # с каскадом по потомкам
```

* ```pending```-потомки → сразу ```canceled```.
* ```running```-потомки → флаг ```cancel_requested```; воркер увидит при ```cancel_check()```.

Внутри команды:

```pycon
def execute(context):
    for i in range(1000):
        if context.get('cancel_check') and context['cancel_check']():
            print("Отмена запрошена")
            return 130
        ...
```

## Режимы воркера

* ```threads``` — быстро, общий процесс, I/O-bound.
* ```processes``` — CPU-bound, ```ProcessPoolExecutor```, свой GIL.
* ```subprocess``` — изоляция + жёсткий kill по таймауту.

```execution_mode``` задаётся в ```config.yml``` или флагом:

```bash
homer schedule:run --execution-mode=subprocess --workers=8
```

## Дедлоки
```context['queue'].call()``` блокирует воркер пока ждёт результат.

Если ```max_workers=1```, а команда A вызвала B через ```call()``` — B никогда не выполнится.

Правила:

* ```max_workers >= 2```.
* Для ```call()``` внутри job-ов передавайте ```max_attempts=1```.
* Не делайте длинных цепочек sync-вызовов.

## Гарантии

* **at-least-once**: при падении воркера job может быть перезапущен.
* **at-most-once per tick**: ```acquire_next``` атомарный, только один воркер возьмёт job.
* **идемпотентность** — на вас: пишите команды так, чтобы повторный запуск не вредил.
