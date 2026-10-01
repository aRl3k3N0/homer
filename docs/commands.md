# Обзор команд

## Синтаксис

```bash
homer <команда> [--ключ=значение ...] [--флаг] [позиционные...]
```

## Пространства имён

Команда ```foo:bar``` соответствует файлу ```commands/foo/bar.py```.

Команда ```foo``` (без ```:```) — файл ```commands/foo.py``` или ```commands/foo/main.py```.

## Список команд

```bash
homer                    # все команды с описаниями
homer list               # то же
homer help               # то же
```

## Запуск команд

```bash
homer idm
homer cmdb:update --cluster=cmdb
homer report:daily --period=2026-09 --to=ops@example.com --dry-run
```

## Встроенные vs пользовательские

* **Пользовательские** — файлы в ```commands/```.
* **Встроенные** — ```lib/commands/```, всегда доступны: ```shell```, ```make:*```, ```schedule:*```, ```queue:*```, ```notify:*```, ```mail:*```.

Пользовательская команда с тем же именем **перекрывает** встроенную.

## Категории встроенных

### Разработка

* ```shell``` — интерактивный REPL
* ```make:command``` — создать новую команду

### Cron-планировщик

* ```schedule:add```, ```schedule:list```, ```schedule:remove```
* ```schedule:enable```, ```schedule:disable```
* ```schedule:run```, ```schedule:tick```

### Очередь

* ```queue:push```, ```queue:list```, ```queue:status```
* ```queue:cancel```, ```queue:retry```, ```queue:purge```
* ```queue:work```

### Проверки

* ```mail:check``` — проверить mailer
* ```notify:test``` — проверить нотификаторы
