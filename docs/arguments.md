# Аргументы командной строки

## Формат

```bash
homer <команда> [--key=value ...] [--flag] [pos1 pos2 ...]
```

## Парсинг

```pycon
def execute(context):
    args = context['args']

    # --user=cmdb         → args['user'] == 'cmdb'
    # --ver=16            → args['ver'] == 16 (int)
    # --active=true       → args['active'] == True
    # --dry-run           → args['dry-run'] == True (флаг)
    # pos1 pos2           → args['_positional'] == ['pos1', 'pos2']
```

## Автоматическое приведение типов

| **Вход**                      | **Результат**          |
|-------------------------------|------------------------|
| ```--port=8080```             | ```int```              |
| ```--ratio=3.14```            | ```float```            |
| ```--active=true```           | ```bool``` ```True```  |
| ```--active=false```          | ```bool``` ```False``` |
| ```--user=cmdb```             | ```str```              |
| ```--dry-run``` (без ```=```) | ```bool``` ```True```  |

## Использование

```pycon
def execute(context):
    args = context['args']

    if not args.get('user'):
        print("Ошибка: --user обязателен")
        return 1

    user = args.get('user')
    ver = args.get('ver', 'latest')
    dry_run = args.get('dry-run', False)
    positional = args.get('_positional', [])
    ...
```

## Сложные значения — вручную

Для словарей/списков удобно передавать как строку и парсить самим:

```bash
homer report:daily --to='a@b.c,b@c.d' --tags='x=1,y=2'
```

```pycon
def _parse_list(raw):
    return [s.strip() for s in (raw or '').split(',') if s.strip()]

def _parse_kv(raw):
    result = {}
    for item in (raw or '').split(','):
        if '=' in item:
            k, v = item.split('=', 1)
            result[k.strip()] = v.strip()
    return result
```

## API ```ArgumentParser```

Если нужно парсить аргументы внутри кода:

```pycon
from lib.arguments import ArgumentParser

p = ArgumentParser()
p.parse(['cmdb:update', '--user=cmdb', '--ver=16'])
p.command        # 'cmdb:update'
p.options        # {'user': 'cmdb', 'ver': 16}
p.flags          # set()  — здесь только флаги
p.get('user')    # 'cmdb'
p.has('user')    # True
```
