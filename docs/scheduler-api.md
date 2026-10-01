# API: Scheduler

Модуль `lib.scheduler`. Cron-планировщик + обработка очереди.

## Компоненты

- `DBStorage` — таблица `homer_tasks`.
- `CronExpression` — парсер cron.
- `Scheduler` — главный цикл: `tick()` + `process_queue()`.

## Cron

5 полей: `минута час день месяц день_недели`.

```bash
0 3 * * *         # каждый день в 03:00
*/5 * * * *       # каждые 5 минут
0 9-18 * * 1-5    # каждый час 9..18, Пн-Пт
0 0 1 * *         # 1-го числа в полночь
0 0 * * 0         # каждое воскресенье
```

## Поддерживаются:

* ```*```, ```*/N```, ```A-B```, ```A,B,C```, ```A-B/N```;
* ```0``` и ```7``` — воскресенье.

## CLI

```bash
homer schedule:add --name=daily-cmdb \
  --command=cmdb:update \
  --cron='0 3 * * *' \
  --args=user=cmdb,ver=16 \
  --description='Ночное обновление'

homer schedule:list
homer schedule:enable  --name=daily-cmdb
homer schedule:disable --name=daily-cmdb
homer schedule:remove  --name=daily-cmdb

homer schedule:tick                    # один проход (для системного cron)
homer schedule:run --interval=30       # цикл (для демона)
```

Флаги ```schedule:run```/```tick```:

* ```--interval=N``` — период проверки (сек).
* ```--workers=N``` — параллельных задач.
* ```--execution-mode=threads|processes|subprocess```.
* ```--lease-seconds=N``` — срок аренды.
* ```--heartbeat-interval=N``` — частота heartbeat.
* ```--job-timeout=N``` — таймаут для subprocess.

## Конфигурация

```yaml
scheduler:
  storage: postgres
  interval: 30
  lease_seconds: 300
  heartbeat_interval: 30
  max_workers: 4
  execution_mode: threads
  job_timeout_sec: 3600
  cancel_children_on_fail: true
  postgres: { ... }
```

## Распределённый запуск

Несколько серверов на одной БД:

* ```tick()``` — атомарный ```UPDATE ... WHERE lease_until IS NULL OR lease_until < now```
гарантирует, что **только один** инстанс возьмёт задачу.
* ```process_queue()``` — тоже атомарный ```acquire_next``` (Postgres: ```FOR UPDATE SKIP LOCKED```).
* ```run_id``` + heartbeat защищают от «зомби»: если процесс упал — другой подберёт job через ```lease_seconds```.

## Сценарии развёртывания

### Один узел (всё в одном)

```bash
homer schedule:run --interval=30
```

### Разделение cron и воркеров

| Узел            | Команда                              | Роль                |
|-----------------|--------------------------------------|---------------------|
| ```cron-01```   | ```homer schedule:run --workers=0``` | Только ```tick()``` |
| ```worker-01``` | ```homer queue:work --workers=8```   | Только очередь      |
| ```worker-02``` | ```homer queue:work --workers=8```   | Только очередь      |

### Всё на всех узлах

Каждый узел: ```homer schedule:run``` — всё сходится к одному выполнению на job благодаря атомарным UPDATE.

## Ошибки cron

Невалидный cron у одной задачи **не роняет планировщик**:

* ```CronExpression``` бросает ```ValueError``` → ловится в ```tick()```, пишется в лог, задача пропускается.
* Ошибка выполнения конкретного job-а — пишется в ```homer_queue.error```, job помечается ```failed```, остальные продолжают.
* Фатальные падения процесса — покрываются перезапуском через ```systemd```/```docker```.

## Программное использование

```pycon
from lib.scheduler import create_storage
from lib.scheduler.runner import Scheduler
from lib.command_loader import CommandLoader

storage = create_storage(config)
loader = CommandLoader(root_dir / 'commands')

sched = Scheduler(
    storage=storage,
    command_loader=loader,
    config=config,
    logger=logger,
    root_dir=root_dir,
    lease_seconds=300,
    max_workers=4,
    execution_mode='threads',
)
sched.run_loop(interval=30)
```

## Своё хранилище

Таблица ```homer_tasks``` создаётся автоматически в БД из ```scheduler.storage```.

Схема (SQLite/Postgres/Oracle) — единая по смыслу:

```
id, name, command, args, cron, enabled, description,
last_run, last_status, last_error, next_run,
locked_by, lease_until, run_id, heartbeat_at
```

Уникальный ключ — ```name```.
