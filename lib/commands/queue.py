"""
Управление очередью Homer + внутренний entrypoint для subprocess.
"""
import os
import sys
from datetime import datetime, timedelta

from lib.console import console, Color

DESCRIPTIONS = {
    'push':   "Put the task in the queue",
    'list':   "Show tasks in the queue",
    'status': "Queue statistics",
    'cancel': "Cancel the task by ID (with cascade)",
    'retry':  "Reassign the task by ID.",
    'purge':  "Delete old completed tasks",
    'work':   "Run the queue worker (without cron)",
}


def _make_queue(context):
    from lib.queue import QueueStorage
    return QueueStorage(context['config'])


def _parse_args_kv(raw):
    if not raw:
        return {}
    result = {}
    for item in str(raw).split(','):
        item = item.strip()
        if not item:
            continue
        if '=' not in item:
            raise ValueError(f"It is expected key=value: '{item}'")
        k, v = item.split('=', 1)
        if v.lower() in ('true', 'yes', '1'):
            v = True
        elif v.lower() in ('false', 'no', '0'):
            v = False
        elif v.isdigit():
            v = int(v)
        result[k.strip()] = v
    return result


def push(context):
    args = context['args']
    command = args.get('command')
    if not command:
        console.error("Mandatory parameter: --command")
        console.comment(
            "Example: homer queue:push --command=cmdb:update "
            "--args=user=cmdb,ver=16 --priority=10"
        )
        return 1
    try:
        cmd_args = _parse_args_kv(args.get('args'))
    except ValueError as e:
        console.error(str(e)); return 1

    from lib.queue import QueueStorage, Dispatcher
    storage = QueueStorage(context['config'])
    try:
        d = Dispatcher(storage, config=context['config'],
                       triggered_by='cli')
        run_at = None
        if args.get('delay'):
            run_at = datetime.now() + timedelta(seconds=int(args['delay']))
        job_id = d.push(
            command,
            priority=int(args.get('priority', 0)),
            run_at=run_at,
            max_attempts=(int(args['max-attempts'])
                          if args.get('max-attempts') else None),
            retry_delay=(int(args['retry-delay'])
                         if args.get('retry-delay') else None),
            timeout_sec=(int(args['timeout']) if args.get('timeout') else None),
            **cmd_args,
        )
        console.success(f"The task has been added: job #{job_id}")
        console.key_value('Team', command)
        console.key_value('Arguments', str(cmd_args))
        if run_at:
            console.key_value('Launch after',
                              run_at.strftime('%Y-%m-%d %H:%M:%S'))
    finally:
        storage.close()
    return 0


def list_tasks(context):
    from lib.queue import QueueStorage
    storage = QueueStorage(context['config'])
    try:
        status_filter = context['args'].get('status')
        jobs = storage.list(status=status_filter, limit=200)
        if not jobs:
            console.warning("The queue is empty."); return 0
        rows = []
        for j in jobs:
            rows.append([
                j.id, j.command, _fmt_args(j.args), j.priority,
                _colorize_status(j.status),
                f"{j.attempts}/{j.max_attempts}",
                j.triggered_by or '—',
                j.created_at.strftime('%H:%M:%S') if j.created_at else '—',
                j.finished_at.strftime('%H:%M:%S') if j.finished_at else '—',
            ])
        console.table(
            headers=['ID', 'Team', 'Arguments', 'P', 'Status',
                     'Try', 'A source', 'Created', 'Completed'],
            rows=rows,
            align=['r', 'l', 'l', 'r', 'c', 'c', 'l', 'l', 'l'],
        )
    finally:
        storage.close()
    return 0


def _fmt_args(args):
    if not args:
        return ''
    return ' '.join(f'{k}={v}' for k, v in args.items())


def _colorize_status(status):
    mapping = {
        'pending':  Color.BRIGHT_YELLOW,
        'running':  Color.BRIGHT_CYAN,
        'done':     Color.BRIGHT_GREEN,
        'failed':   Color.BRIGHT_RED,
        'canceled': Color.BRIGHT_BLACK,
        'timeout':  Color.BRIGHT_MAGENTA,
    }
    return console.colored(status, mapping.get(status, Color.WHITE))


def status(context):
    from lib.queue import QueueStorage
    storage = QueueStorage(context['config'])
    try:
        s = storage.stats()
        console.section("Queue statistics")
        for k in ('pending', 'running', 'done', 'failed',
                  'canceled', 'timeout'):
            console.key_value(k, s.get(k, 0))
    finally:
        storage.close()
    return 0


def cancel(context):
    job_id = context['args'].get('id')
    if not job_id:
        console.error("Specify --id"); return 1
    from lib.queue import QueueStorage
    storage = QueueStorage(context['config'])
    try:
        cascade = not context['args'].get('no-cascade', False)
        n = storage.cancel(int(job_id), cascade=cascade)
        if n:
            console.success(f"Tasks have been cancelled: {n}")
        else:
            console.error(f"It was not possible to cancel #{job_id}")
            return 1
    finally:
        storage.close()
    return 0


def retry(context):
    job_id = int(context['args'].get('id') or 0)
    if not job_id:
        console.error("Specify --id"); return 1
    from lib.queue import QueueStorage
    from lib.queue.models import JobStatus
    storage = QueueStorage(context['config'])
    try:
        job = storage.get(job_id)
        if not job:
            console.error(f"No job #{job_id}"); return 1
        if job.status not in (JobStatus.FAILED, JobStatus.TIMEOUT,
                              JobStatus.CANCELED):
            console.error(f"Job #{job_id} в статусе {job.status}; retry не нужен")
            return 1
        storage.retry(job_id)
        console.success(f"Job #{job_id} перепоставлен в очередь")
    finally:
        storage.close()
    return 0


def purge(context):
    older = int(context['args'].get('older', 86400))
    from lib.queue import QueueStorage
    storage = QueueStorage(context['config'])
    try:
        n = storage.purge(older_than_seconds=older)
        console.success(f"Удалено {n} задач старше {older}с")
    finally:
        storage.close()
    return 0


def work(context):
    """
    Воркер, который обрабатывает ТОЛЬКО очередь (без cron).
    Полезно, если cron обслуживает отдельный инстанс.
    """
    from lib.scheduler.runner import Scheduler
    from lib.command_loader import CommandLoader
    from lib.scheduler import create_storage
    from lib.notify import NotifyManager

    cfg = context['config']
    sched_cfg = cfg.get('scheduler', {}) or {}

    class QueueOnlyScheduler(Scheduler):
        def tick(self):
            pass

    cron_storage = create_storage(cfg)
    loader = CommandLoader(context['root_dir'] / 'commands')
    notify_manager = NotifyManager(
        cfg,
        logger=context['logger'],
        root_dir=context['root_dir'],
    )

    scheduler = QueueOnlyScheduler(
        storage=cron_storage,
        command_loader=loader,
        config=cfg,
        logger=context['logger'],
        root_dir=context['root_dir'],
        lease_seconds=int(sched_cfg.get('lease_seconds', 300)),
        heartbeat_interval=int(sched_cfg.get('heartbeat_interval', 30)),
        max_workers=int(context['args'].get('workers')
                        or sched_cfg.get('max_workers', 4)),
        execution_mode=context['args'].get('execution-mode')
                       or sched_cfg.get('execution_mode', 'threads'),
        notify_manager=notify_manager,
    )

    interval = int(context['args'].get('interval', 2))
    try:
        scheduler.run_loop(interval=interval)
    finally:
        cron_storage.close()
    return 0


# ─────────────────── Внутренний entrypoint для subprocess ───────────────────

def run_job_subprocess_entry(context):
    """
    `homer _run-job --id=N`
    Запускается как отдельный процесс воркером-родителем.
    Выполняет job из очереди и пишет результат.
    """
    # Восстанавливаем trace context из TRACEPARENT
    traceparent = os.environ.get('TRACEPARENT')
    if traceparent:
        try:
            from opentelemetry.trace import TraceContext, TraceFlags, set_span_in_context
            from opentelemetry import context as otel_context
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

            propagator = TraceContextTextMapPropagator()
            ctx = propagator.extract({'traceparent': traceparent})
            otel_context.attach(ctx)
        except Exception:
            pass

    from lib.tracing import setup_tracing
    setup_tracing(context['config'], service_name='homer-job')

    job_id = context['args'].get('id')
    if not job_id:
        print("_run-job: --id обязателен", file=sys.stderr)
        return 2
    job_id = int(job_id)

    from lib.queue import QueueStorage
    from lib.arguments import ArgumentParser

    storage = QueueStorage(context['config'])
    try:
        job = storage.get(job_id)
        if not job:
            print(f"_run-job: job #{job_id} не найден", file=sys.stderr)
            return 2

        parts = [job.command]
        for k, v in (job.args or {}).items():
            if isinstance(v, bool):
                if v:
                    parts.append(f'--{k}')
            else:
                parts.append(f'--{k}={v}')

        parser = ArgumentParser()
        parser.parse(parts)

        commands = context['commands']
        cmd_name = parser.command
        if cmd_name not in commands:
            print(f"_run-job: команда '{cmd_name}' не найдена", file=sys.stderr)
            return 2

        def cancel_check():
            return storage.is_cancel_requested(job_id)

        ctx = {
            'config': context['config'],
            'logger': context['logger'],
            'args': parser.options,
            'root_dir': context['root_dir'],
            'command_name': cmd_name,
            'cancel_check': cancel_check,
        }
        from lib.queue import Dispatcher
        dispatcher = Dispatcher(storage, config=context['config'],
                                triggered_by=f"job#{job_id}")
        dispatcher._parent_job_id = job_id
        ctx['queue'] = dispatcher

        if storage.is_cancel_requested(job_id):
            return 130

        result = commands[cmd_name]['execute'](ctx)
        return 0 if result in (None, 0, True) else int(result)
    finally:
        storage.close()
