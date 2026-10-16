"""
Команды управления планировщиком.
"""
from homer.core.console import console, Color
from homer.scheduler import create_storage, CronExpression
from homer.scheduler.runner import Scheduler
from homer.core.command_loader import CommandLoader
from homer.notify import NotifyManager


DESCRIPTIONS = {
    'add':     "Добавить задачу в планировщик",
    'list':    "Список задач планировщика",
    'remove':  "Удалить задачу",
    'enable':  "Включить задачу",
    'disable': "Отключить задачу",
    'run':     "Запустить планировщик в цикле",
    'tick':    "Проверить и выполнить задачи (однократно)",
}


# ─────────────────────────── helpers ───────────────────────────

def _make_scheduler(context, queue_only=False):
    """
    Собирает Scheduler с учётом всех опций из конфига и CLI.
    """
    cfg = context['config']
    sched_cfg = cfg.get('scheduler', {}) or {}
    args = context['args']

    storage = create_storage(cfg)
    loader = CommandLoader(context['root_dir'] / 'commands')

    notify_manager = NotifyManager(
        cfg,
        logger=context['logger'],
        root_dir=context['root_dir'],
    )

    # Опции можно переопределять из CLI
    lease_seconds = int(args.get('lease-seconds')
                        or sched_cfg.get('lease_seconds', 300))
    heartbeat_interval = int(args.get('heartbeat-interval')
                             or sched_cfg.get('heartbeat_interval', 30))
    max_workers = int(args.get('workers')
                      or sched_cfg.get('max_workers', 4))
    execution_mode = (args.get('execution-mode')
                      or sched_cfg.get('execution_mode', 'threads'))
    job_timeout_sec = int(args.get('job-timeout')
                          or sched_cfg.get('job_timeout_sec', 3600))

    # QueueOnlyScheduler — отключает tick() (для очереди без cron)
    cls = Scheduler
    if queue_only:
        class QueueOnlyScheduler(Scheduler):
            def tick(self):
                pass
        cls = QueueOnlyScheduler

    scheduler = cls(
        storage=storage,
        command_loader=loader,
        config=cfg,
        logger=context['logger'],
        root_dir=context['root_dir'],
        lease_seconds=lease_seconds,
        heartbeat_interval=heartbeat_interval,
        max_workers=max_workers,
        execution_mode=execution_mode,
        config_path=cfg.config_path,
        notify_manager=notify_manager,
        job_timeout_sec=job_timeout_sec,
    )
    return scheduler


def _parse_args_kv(raw):
    """--args=user=cmdb,ver=16 → {'user':'cmdb','ver':16}"""
    if not raw:
        return {}
    result = {}
    for item in str(raw).split(','):
        item = item.strip()
        if not item:
            continue
        if '=' not in item:
            raise ValueError(f"Ожидается key=value: '{item}'")
        k, v = item.split('=', 1)
        if v.lower() in ('true', 'yes', '1'):
            v = True
        elif v.lower() in ('false', 'no', '0'):
            v = False
        elif v.isdigit():
            v = int(v)
        result[k.strip()] = v
    return result


def _fmt_args(args):
    if not args:
        return ''
    return ' '.join(f'{k}={v}' for k, v in args.items())


# ─────────────────────────── Команды cron ───────────────────────────

def add(context):
    args = context['args']
    name = args.get('name')
    command = args.get('command')
    cron = args.get('cron')

    if not name or not command or not cron:
        console.error("Обязательные параметры: --name, --command, --cron")
        console.comment(
            "Пример: homer schedule:add --name=daily-cmdb "
            "--command=cmdb:update --cron='0 3 * * *' "
            "--args=user=cmdb,ver=16"
        )
        return 1

    try:
        CronExpression(cron)
    except ValueError as e:
        console.error(f"Некорректный cron: {e}")
        return 1

    try:
        task_args = _parse_args_kv(args.get('args'))
    except ValueError as e:
        console.error(str(e))
        return 1

    storage = create_storage(context['config'])
    try:
        if storage.get_by_name(name):
            console.error(f"Задача с именем '{name}' уже существует")
            return 1

        from homer.scheduler.base import Task
        task = Task(
            name=name,
            command=command,
            args=task_args,
            cron=cron,
            enabled=True,
            description=args.get('description', ''),
        )
        tid = storage.add(task)
        console.success(f"Задача добавлена (id={tid})")
        console.key_value('Имя', name)
        console.key_value('Команда', command)
        console.key_value('Cron', cron)
        console.key_value('Аргументы', str(task_args))
    finally:
        storage.close()
    return 0


def list_tasks(context):
    storage = create_storage(context['config'])
    try:
        tasks = storage.list()
        if not tasks:
            console.warning("Задач нет")
            return 0

        rows = []
        for t in tasks:
            rows.append([
                t.id,
                t.name,
                t.command + (f" ({_fmt_args(t.args)})" if t.args else ''),
                t.cron,
                console.colored('вкл', Color.BRIGHT_GREEN) if t.enabled
                    else console.colored('выкл', Color.BRIGHT_BLACK),
                t.last_status or '—',
                t.last_run.strftime('%Y-%m-%d %H:%M') if t.last_run else '—',
            ])
        console.table(
            headers=['ID', 'Имя', 'Команда', 'Cron',
                     'Состояние', 'Статус', 'Последний запуск'],
            rows=rows,
            align=['r', 'l', 'l', 'l', 'c', 'l', 'l'],
        )
    finally:
        storage.close()
    return 0


def remove(context):
    name = context['args'].get('name')
    if not name:
        console.error("Укажите --name")
        return 1

    storage = create_storage(context['config'])
    try:
        task = storage.get_by_name(name)
        if not task:
            console.error(f"Задача '{name}' не найдена")
            return 1
        storage.remove(task.id)
        console.success(f"Задача '{name}' удалена")
    finally:
        storage.close()
    return 0


def enable(context):
    return _toggle(context, True)


def disable(context):
    return _toggle(context, False)


def _toggle(context, enabled):
    name = context['args'].get('name')
    if not name:
        console.error("Укажите --name")
        return 1

    storage = create_storage(context['config'])
    try:
        task = storage.get_by_name(name)
        if not task:
            console.error(f"Задача '{name}' не найдена")
            return 1
        task.enabled = enabled
        storage.update(task)
        state = 'включена' if enabled else 'отключена'
        console.success(f"Задача '{name}' {state}")
    finally:
        storage.close()
    return 0


def run_loop(context):
    """Полный цикл: cron + обработка очереди в одном процессе."""
    interval = context['args'].get('interval') or \
               context['config'].get('scheduler.interval', 30)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = 30

    scheduler = _make_scheduler(context, queue_only=False)
    try:
        scheduler.run_loop(interval=interval)
    finally:
        scheduler.storage.close()
        try:
            scheduler.queue.close()
        except Exception:
            pass
    return 0


def tick(context):
    """
    Однократная проверка cron-задач и разбор очереди.
    Удобно вызывать из системного cron каждую минуту.
    """
    scheduler = _make_scheduler(context, queue_only=False)
    try:
        scheduler.tick()
        scheduler.process_queue()
        console.success("Проверка выполнена")
    finally:
        scheduler.storage.close()
        try:
            scheduler.queue.close()
        except Exception:
            pass
    return 0