# Встроенные команды

Живут в `lib/commands/`. Всегда доступны, регистрируются через `BUILTIN_COMMANDS`.

Пользовательская команда с тем же именем перекрывает встроенную.

## Разработка

### `shell`

```bash
homer shell
```

Интерактивный REPL. См. [shell.md](shell.md).

### ```make:command```

```bash
homer make:command --name=report:daily \
  --description="Ежедневный отчёт" \
  --args_example="'period': 'today'"
```

Флаги:

* ```--force``` — перезаписать существующий файл.
* ```--description```, ```--args_example```.

## Cron-планировщик

### ```schedule:add```

```bash
homer schedule:add --name=daily-cmdb \
  --command=cmdb:update \
  --cron='0 3 * * *' \
  --args=user=cmdb,ver=16 \
  --description='Ночное обновление'
```

### ```schedule:list```

```bash
homer schedule:list
```

### ```schedule:enable``` / ```schedule:disable```

```bash
homer schedule:disable --name=daily-cmdb
homer schedule:enable  --name=daily-cmdb
```

### ```schedule:remove```

```bash
homer schedule:remove --name=daily-cmdb
```

### ```schedule:run```

Полный цикл (cron + очередь).

```bash
homer schedule:run --interval=30 --workers=4 --execution-mode=threads
```

### ```schedule:tick```

Один проход. Удобно для системного cron:

```bash
* * * * * cd /opt/homer && ./homer schedule:tick >> logs/cron.log 2>&1
```

## Очередь

### ```queue:push```

```bash
homer queue:push --command=cmdb:update --args=user=cmdb,ver=16 \
  --priority=10 --max-attempts=5 --retry-delay=120 --timeout=600 \
  --delay=300
```

### ```queue:list```

```bash
homer queue:list [--status=pending|running|done|failed|canceled|timeout]
```

### ```queue:status```

Счётчики по статусам.

### ```queue:cancel```

```bash
homer queue:cancel --id=42 [--no-cascade]
```

### ```queue:retry```

```bash
homer queue:retry --id=42
```

### ```queue:purge```

```bash
homer queue:purge --older=86400
```

### ```queue:work```

Воркер только очереди (без cron). Полезно для отдельного узла.

```bash
homer queue:work --interval=2 --workers=8 --execution-mode=subprocess
```

## Проверки

### ```mail:check```

```bash
homer mail:check
```

Показывает транспорт, отправителя, папку шаблонов и список шаблонов.

### ```notify:test```

```bash
homer notify:test --status=failed
homer notify:test --status=done
homer notify:test --status=timeout
```

## Скрытые

### ```_run-job```

Внутренняя команда. Вызывается воркером в ```execution_mode=subprocess```. Не запускайте вручную.
