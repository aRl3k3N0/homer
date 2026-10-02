"""
Управление Scheduler в фоне (start/stop/restart/reload/status).

Внутренняя команда _schedule_run — сам процесс планировщика.
"""
import os
import signal
import sys
import time
from pathlib import Path

from lib.console import console, Color
from lib.daemon import ServiceManager, ServiceStatus


DESCRIPTIONS = {
    'start':   "Запустить планировщик в фоне",
    'stop':    "Остановить планировщик",
    'restart': "Перезапустить планировщик",
    'reload':  "Перечитать конфиг и перезагрузить плагины (SIGHUP)",
    'status':  "Статус планировщика",
    'logs':    "Хвост лога планировщика",
}


def _manager(context) -> ServiceManager:
    return ServiceManager(
        Path(context['root_dir']), 'schedule',
        config=context['config'],
    )


def _homer_argv(context) -> list[str]:
    root = Path(context['root_dir'])
    homer = root / 'homer'
    argv = [sys.executable, str(homer), '_schedule_run']
    args = context['args']
    for key in ('interval', 'workers', 'execution-mode', 'job-timeout',
                'lease-seconds', 'heartbeat-interval'):
        if args.get(key):
            argv.append(f"--{key}={args[key]}")
    return argv


# ─────────── Публичные ───────────

def start(context):
    mgr = _manager(context)
    st = mgr.status()

    if st.status == ServiceStatus.RUNNING:
        console.warning(f"Scheduler уже запущен (pid {st.pid})")
        return 0

    if st.status == ServiceStatus.STALE:
        console.comment("Обнаружен stale PID — очищаю")
        mgr.stop()

    argv = _homer_argv(context)
    try:
        st = mgr.start(argv)
    except Exception as e:
        console.error(f"Не удалось запустить: {e}")
        return 1

    if st.status == ServiceStatus.RUNNING:
        console.success(f"Scheduler запущен (pid {st.pid})")
        console.key_value('Лог', str(st.log_file))
        console.key_value('PID-файл', str(st.pid_file))
        console.comment("Остановить: homer scheduler:stop")
        return 0
    console.error(f"Не удалось запустить (статус: {st.status})")
    return 1


def stop(context):
    mgr = _manager(context)
    st = mgr.status()
    if st.status == ServiceStatus.STOPPED:
        console.comment("Scheduler не запущен")
        return 0
    if st.status == ServiceStatus.STALE:
        mgr.stop()
        return 0
    console.info(f"Останавливаю (pid {st.pid})…")
    mgr.stop()
    console.success("Scheduler остановлен")
    return 0


def restart(context):
    mgr = _manager(context)
    st = mgr.status()
    if st.status == ServiceStatus.RUNNING:
        console.info(f"Останавливаю (pid {st.pid})…")
        mgr.stop()
        time.sleep(0.5)
    try:
        st = mgr.start(_homer_argv(context), force=True)
    except Exception as e:
        console.error(f"Не удалось запустить: {e}")
        return 1
    if st.status == ServiceStatus.RUNNING:
        console.success(f"Scheduler перезапущен (pid {st.pid})")
        return 0
    console.error("Не удалось перезапустить")
    return 1


def reload(context):
    mgr = _manager(context)
    st = mgr.status()
    if st.status != ServiceStatus.RUNNING:
        console.error("Scheduler не запущен")
        return 1
    mgr.reload()
    console.success(f"SIGHUP отправлен процессу {st.pid}")
    console.comment("Планировщик перечитает config.yml и перезагрузит плагины")
    return 0


def status(context):
    mgr = _manager(context)
    st = mgr.status()

    status_color = {
        ServiceStatus.RUNNING:  Color.BRIGHT_GREEN,
        ServiceStatus.STOPPED:  Color.BRIGHT_BLACK,
        ServiceStatus.STALE:    Color.BRIGHT_YELLOW,
    }.get(st.status, Color.WHITE)

    console.banner("Scheduler", st.status, color=status_color)
    console.key_value('Статус', console.colored(st.status, status_color))
    if st.pid:
        console.key_value('PID', st.pid)
    if st.started_at:
        console.key_value('Запущен', st.started_at.strftime('%Y-%m-%d %H:%M:%S'))
    if st.uptime:
        console.key_value('Uptime', _fmt_uptime(st.uptime))
    console.key_value('PID-файл', str(st.pid_file))
    console.key_value('Лог', str(st.log_file))

    if st.status == ServiceStatus.RUNNING:
        # Дополнительно — счётчики из очереди
        try:
            from lib.queue import QueueStorage
            storage = QueueStorage(context['config'])
            try:
                stats = storage.stats()
                console.section("Очередь")
                for k in ('pending', 'running', 'done', 'failed',
                          'canceled', 'timeout'):
                    console.key_value(k, stats.get(k, 0))
            finally:
                storage.close()
        except Exception:
            pass
    return 0


def logs(context):
    mgr = _manager(context)
    st = mgr.status()
    if not st.log_file or not Path(st.log_file).exists():
        console.warning("Лог-файл отсутствует")
        return 0
    n = int(context['args'].get('lines', 50))
    lines = Path(st.log_file).read_text(
        encoding='utf-8', errors='replace',
    ).splitlines()
    console.section(f"Хвост лога — {st.log_file.name} ({n} строк)")
    for line in lines[-n:]:
        print(line)
    return 0


# ─────────── Внутренняя ───────────

def _run(context):
    """Реальный процесс планировщика."""
    from lib.scheduler.runner import Scheduler
    from lib.scheduler import create_storage
    from lib.command_loader import CommandLoader
    from lib.notify import NotifyManager
    from lib.logger import Logger

    cfg = context['config']
    root = Path(context['root_dir'])
    args = context['args']
    sched_cfg = cfg.get('scheduler', {}) or {}

    logger = Logger(cfg, root)

    cron_storage = create_storage(cfg)
    loader = CommandLoader(root / 'commands')
    notify_manager = NotifyManager(cfg, logger=logger, root_dir=root)

    scheduler = Scheduler(
        storage=cron_storage,
        command_loader=loader,
        config=cfg,
        logger=logger,
        root_dir=root,
        lease_seconds=int(args.get('lease-seconds')
                          or sched_cfg.get('lease_seconds', 300)),
        heartbeat_interval=int(args.get('heartbeat-interval')
                               or sched_cfg.get('heartbeat_interval', 30)),
        max_workers=int(args.get('workers')
                        or sched_cfg.get('max_workers', 4)),
        execution_mode=args.get('execution-mode')
                       or sched_cfg.get('execution_mode', 'threads'),
        config_path=cfg.config_path,
        notify_manager=notify_manager,
        job_timeout_sec=int(args.get('job-timeout')
                            or sched_cfg.get('job_timeout_sec', 3600)),
    )

    # ── Сигналы ──
    def _on_term(signum, frame):
        logger.info("[scheduler] SIGTERM — остановка")
        scheduler.stop()

    def _on_hup(signum, frame):
        logger.info("[scheduler] SIGHUP — перечитываю конфиг и плагины")
        try:
            cfg.load()
            from lib.plugins import get_manager
            from lib.plugins.reload import PluginReloader
            mgr = get_manager()
            mgr.discover(root / 'plugins', cfg)
            reloader = PluginReloader(
                mgr, root_dir=root, config=cfg,
                homer_context={'config': cfg, 'logger': logger,
                               'root_dir': root},
            )
            results = reloader.reload_all()
            for name, ok in results.items():
                logger.info(f"[scheduler] плагин '{name}' "
                            f"{'перезагружен' if ok else 'ошибка reload'}")
        except Exception as e:
            logger.error(f"[scheduler] reload: {e}", exc_info=True)

    signal.signal(signal.SIGTERM, _on_term)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, _on_term)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, _on_hup)

    interval = int(args.get('interval')
                   or sched_cfg.get('interval', 30))

    logger.info(f"[scheduler] Старт (pid {os.getpid()}, interval={interval})")
    try:
        scheduler.run_loop(interval=interval)
    finally:
        try:
            cron_storage.close()
        except Exception:
            pass
        logger.info("[scheduler] Остановлен")
    return 0


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"

def services_status(context):
    """Статус всех известных сервисов."""
    from pathlib import Path
    from lib.daemon import ServiceManager, ServiceStatus

    root = Path(context['root_dir'])
    names = ['webui', 'schedule']

    rows = []
    for name in names:
        mgr = ServiceManager(root, name)
        st = mgr.status()
        color = {
            ServiceStatus.RUNNING: 'да',
            ServiceStatus.STOPPED: 'нет',
            ServiceStatus.STALE:   'stale',
        }.get(st.status, st.status)
        rows.append([
            name,
            color,
            st.pid or '—',
            _fmt_uptime(st.uptime) if st.uptime else '—',
        ])
    console.table(
        headers=['Сервис', 'Работает', 'PID', 'Uptime'],
        rows=rows,
        align=['l', 'c', 'r', 'r'],
    )
    return 0

def pause(context):
    """SIGSTOP планировщику — процесс останавливается."""
    import os
    import signal
    from pathlib import Path
    from lib.daemon import ServiceManager

    mgr = ServiceManager(Path(context['root_dir']), 'scheduler',
                         config=context['config'])
    st = mgr.status()
    if st.status != 'running':
        console.error("Scheduler не запущен")
        return 1
    os.kill(st.pid, signal.SIGSTOP)
    console.success(f"SIGSTOP отправлен {st.pid} (paused)")
    return 0


def resume(context):
    """SIGCONT — продолжить."""
    import os
    import signal
    from pathlib import Path
    from lib.daemon import ServiceManager

    mgr = ServiceManager(Path(context['root_dir']), 'scheduler',
                         config=context['config'])
    st = mgr.status()
    if st.status != 'running':
        console.error("Scheduler не запущен")
        return 1
    os.kill(st.pid, signal.SIGCONT)
    console.success(f"SIGCONT отправлен {st.pid} (resumed)")
    return 0
