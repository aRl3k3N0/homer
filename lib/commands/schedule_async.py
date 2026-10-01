"""
Запуск планировщика в async-режиме.
"""
DESCRIPTION = "Запустить планировщик+воркеры на asyncio"


def execute(context):
    import asyncio

    from lib.scheduler.async_runner import AsyncScheduler
    from lib.scheduler import create_storage
    from lib.command_loader import CommandLoader
    from lib.notify import NotifyManager

    cfg = context['config']
    args = context['args']
    sched_cfg = cfg.get('scheduler', {}) or {}

    cron_storage = create_storage(cfg)
    loader = CommandLoader(context['root_dir'] / 'commands')
    notify_manager = NotifyManager(
        cfg, logger=context['logger'], root_dir=context['root_dir'],
    )

    scheduler = AsyncScheduler(
        storage=cron_storage,
        command_loader=loader,
        config=cfg,
        logger=context['logger'],
        root_dir=context['root_dir'],
        lease_seconds=int(sched_cfg.get('lease_seconds', 300)),
        heartbeat_interval=int(sched_cfg.get('heartbeat_interval', 30)),
        max_workers=int(args.get('workers') or sched_cfg.get('max_workers', 8)),
        notify_manager=notify_manager,
    )

    interval = int(args.get('interval', 30))

    try:
        asyncio.run(scheduler.run_loop(interval=interval))
    except KeyboardInterrupt:
        print()
        context['logger'].info("[asyncio] Остановлен")
    finally:
        cron_storage.close()
    return 0
