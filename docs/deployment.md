# Развёртывание

## systemd

Файл `/etc/systemd/system/homer-scheduler.service`:

```ini
[Unit]
Description=Homer Scheduler
After=network.target postgresql.service

[Service]
Type=simple
User=homer
Group=homer
WorkingDirectory=/opt/homer
ExecStart=/opt/homer/homer schedule:run --interval=30 --workers=8
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/homer/scheduler.log
StandardError=append:/var/log/homer/scheduler.err

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now homer-scheduler
systemctl status homer-scheduler
```

## Через системный cron (только tick)

Если не хотите держать демон, оформите ```schedule:tick``` в crontab:

```bash
* * * * * cd /opt/homer && ./homer schedule:tick >> logs/cron.log 2>&1
```

Подходит, если задач немного и каждая укладывается в минуту. Для тяжёлых — ставьте воркеры (```queue:work```).

## Несколько узлов на одной БД

* ```scheduler.storage: postgres``` (или oracle).
* Все узлы читают один конфиг с теми же параметрами подключения.
* Cron-узел: ```homer schedule:run --workers=0``` (или ```--cron-only``` через свой конфиг).
* Воркеры: ```homer queue:work --workers=N```.

Атомарные ```UPDATE``` в БД гарантируют, что job выполнится один раз.

## Бэкапы

* **SQLite**: просто файл ```var/scheduler.db``` — копируйте при остановленном сервисе или через ```.backup```.
* **Postgres**/**Oracle**: стандартный ```pg_dump```/```expdp```.

## Мониторинг

* ```homer queue:status``` — счётчики.
* ```homer schedule:list``` — что запланировано и когда запускалось.
* Логи: ```logs/*.log``` (по командам и дням).
* Файл-нотификатор: ```var/notifications.jsonl```.
