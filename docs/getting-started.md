# Начало работы

## Первая команда

```bash
./homer make:command --name=hello --description="Поздороваться"
```

Создан файл ```commands/hello.py```:

```pycon
"""hello — Поздороваться"""
DESCRIPTION = "Поздороваться"

def execute(context):
    logger = context['logger']
    command = context['command_name']
    logger.info("Запуск команды hello", command=command)
    print("✅ Команда hello выполнена")
    return 0
```

## Запуск:

```bash
./homer hello
```

## С аргументами

```bash
./homer make:command --name=greet --args_example="'name': 'world'"
```

Внутри:

```pycon
def execute(context):
    name = context['args'].get('name', 'world')
    print(f"Привет, {name}!")
    return 0
```

```bash
./homer greet --name=Иван
# → Привет, Иван!
```

## Cron-задача

```bash
# Каждый час
./homer schedule:add --name=greet-hourly --command=greet --cron='0 * * * *'

# Запустить планировщик + воркеров
./homer schedule:run --interval=30
```

## Следующие шаги

* [Создание команд](creating-commands.md)
* [Аргументы](arguments.md)
* [Конфигурация](configuration.md)
* [Примеры](../examples/README.md)
