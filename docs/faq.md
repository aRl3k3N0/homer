# FAQ

## Что если в cron-задаче ошибка — упадёт ли всё?

Нет. Ошибки локализуются:

- Кривой cron у задачи → ловится, задача пропускается, остальные работают.
- Ошибка выполнения job-а → пишется в БД, статус `failed`, остальные продолжают.
- Фатальное падение процесса (OOM, segfault) — только внешний супервизор (`systemd Restart=on-failure`, Docker `restart: unless-stopped`).

## Как запустить воркеры на нескольких серверах?

Одна БД планировщика (`scheduler.storage: postgres`), у каждого узла:

```bash
homer queue:work --workers=8
```

```acquire_next``` атомарный, job выполнится только один раз.

## Как сделать задачу CPU-bound?

```execution_mode: processes``` в конфиге или ```--execution-mode=processes``` в CLI.

Учтите: соединение с БД создаётся **внутри** воркера (не переиспользуется из родителя).

## Как ограничить время выполнения?

* Для ```subprocess```: ```timeout_sec``` в job-е или ```scheduler.job_timeout_sec```.
* Для ```threads```/```processes```: команда сама должна проверять ```context['cancel_check']()``` или свой таймаут.

## Как отменить job, который уже выполняется?

```bash
homer queue:cancel --id=42
```

Помечается ```cancel_requested = true```. Команда должна периодически проверять ```context['cancel_check']()```. Прямое убийство возможно только в ```subprocess```-режиме.

## Как отправить уведомление из команды?

См. [notifications-from-commands.md](notifications-from-commands.md).

Кратко:

```pycon
from lib.notify import NotifyManager
notify = NotifyManager(context['config'], logger=context['logger'])
notify.emit(my_event)
```

## Почему уведомление не приходит?

Проверьте:

1. ```notifications.enabled``` содержит имя канала.
2. В канале ```on``` включает ваш ```status```.
3. Для Telegram/Slack/Mattermost — задан webhook/token.
4. ```homer notify:test --status=failed``` — тестовое сообщение доходит?
5. Логи Homer (```logs/notify_*.log```) — ошибки отправки.

## Как быстро протестировать письмо без реального SMTP?

```yaml
mailer:
  transport: file
  file:
    dir: var/mail
```

Письма сохранятся в ```var/mail/*.eml```. Откройте любым почтовым клиентом.

## Как посмотреть содержимое очереди?

```bash
homer queue:list
homer queue:status
```

Или прямо в БД:

```sql
SELECT id, command, status, attempts FROM homer_queue ORDER BY id DESC;
```

## Как откатить миграцию схемы?

Homer создаёт таблицы идемпотентно (```CREATE TABLE IF NOT EXISTS```). Новые колонки в старых БД — добавьте вручную через ```ALTER TABLE```.

## Где хранятся логи?

* ```var/logs/<команда>_YYYY-MM-DD.log``` — по одной команде в день.
* ```var/logs/notify_YYYY-MM-DD.log``` — нотификатор.
* ```var/logs/scheduler_YYYY-MM-DD.log``` — планировщик.

## Почему ```queue.call()``` зависает?

* ```max_workers=1``` и внутри — ```call()```, дедлок. Ставьте ```max_workers >= 2```.
* Воркер не запущен (```homer schedule:run``` / ```homer queue:work```).
* Таймаут слишком большой.


## Можно ли использовать свой cron?

Да. Системный cron + ```homer schedule:tick``` каждую минуту — простой вариант без демона.

## Как хранить секреты (пароли БД)?

* Не коммитьте ```config.yml```.
* Заведите ```config.example.yml``` в репо, а реальный ```config.yml``` — локально.
* Для продакшена — env vars + чтение через ```os.environ``` в своём враппере, либо секреты-менеджеры (Vault, KMS).