# Создание команд

## Через генератор

```bash
homer make:command --name=report:daily \
  --description="Ежедневный отчёт" \
  --args_example="'period': 'today', 'to': 'ops@example.com'"
```

Создаст ```commands/report/daily.py``` (с ```__init__.py``` в промежуточных папках).

## Вручную
Файл ```commands/hello.py```:

```pycon
"""
hello — приветствие.
"""
DESCRIPTION = "Поздороваться"

def execute(context):
    name = context['args'].get('name', 'world')
    print(f"Привет, {name}!")
    return 0
```

Ключевое:

* Функция ```execute(context)``` — обязательна.
* ```DESCRIPTION``` — необязательна, показывается в ```homer```.
* Возврат ```int``` — exit code. ```0``` / ```None``` — успех.

## Контекст ```context```

```pycon
{
    'config':       Config,                # config.yml
    'logger':       Logger,                # логирование
    'args':         dict,                  # аргументы CLI
    'root_dir':     Path,                  # корень проекта
    'command_name': str,                   # 'report:daily'
    'commands':     dict,                  # все загруженные команды
    'queue':        Dispatcher,            # ленивый диспетчер очереди
    'cancel_check': callable,              # (опционально) в воркере
}
```

## Имя команды из файла

| **Файл**                            | **Команда**        |
|-------------------------------------|--------------------|
| ```commands/hello.py```             | ```hello```        |
| ```commands/hello/main.py```        | ```hello```        |
| ```commands/report/daily.py```      | ```report:daily``` |
| ```commands/report/daily/main.py``` | ```report:daily``` |
| ```commands/cmdb/update.py```       | ```cmdb:update```  |

## Пример: работа с БД

```pycon
from lib.db import connect

def execute(context):
    config = context['config']
    logger = context['logger']

    with connect('postgres', config, prefix='databases.postgres') as db:
        rows = db.fetchall("SELECT id, name FROM users WHERE active = %s", [True])
        for r in rows:
            logger.info(f"user: {r['id']} {r['name']}", command=context['command_name'])
    return 0
```

## Пример: отправка письма

```pycon
from lib.mailer import Mailer

def execute(context):
    mailer = Mailer(context['config'], context['root_dir'] / 'email')
    mailer.send(
        to='ops@example.com',
        template_name='welcome',
        context={'user': 'Иван', 'version': '1.0'},
    )
    return 0
```

## Пример: вызов другой команды (синхронно)

```pycon
def execute(context):
    queue = context['queue']
    result = queue.call('cmdb:update', user='cmdb', ver=16, timeout=300)
    if not result.ok:
        context['logger'].error(f"Ошибка: {result.error}")
        return 1
    print(result.output)
    return 0
```

## Пример: вызов другой команды (асинхронно)

```pycon
def execute(context):
    job_id = context['queue'].push('report:send', to='ops@example.com')
    print(f"Задача отправлена в очередь: #{job_id}")
    return 0
```

## Отправка уведомления из команды

См. отдельный гайд: [Отправка уведомлений из команды](notifications-from-commands.md).

## Следующие шаги

* [Аргументы](arguments.md)
* [API Config](config-api.md)
* [API DB](db-api.md)
* [API Mailer](mailer-api.md)
* [API Notify](notify-api.md)
* [API Queue](queue-api.md)
* [Примеры](../examples/README.md)