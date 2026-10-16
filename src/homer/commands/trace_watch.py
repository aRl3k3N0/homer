"""
trace:watch — потоковый мониторинг очереди в реальном времени.

Показывает события:
    + created   — задача создана
    ~ updated   — смена статуса/попытки
    - removed   — задача удалена/очищена

Фильтры:
    --status=pending,running      — какие статусы показывать
    --command=cmdb:update         — по имени команды
    --triggered-by=cron:daily     — по источнику
    --follow-children=<id>        — только поддерево конкретной задачи
    --interval=1                  — период опроса БД (сек)

Формат вывода:
    --format=pretty|jsonl|compact
"""
import json
import sys
import time
from datetime import datetime

from homer.core.console import console, Color

DESCRIPTION = "Стриминг всех jobs очереди в реальном времени"


# ─────────── Фильтры ───────────

class Filters:
    def __init__(self, args):
        self.statuses = set()
        raw = args.get('status')
        if raw:
            self.statuses = {s.strip() for s in str(raw).split(',') if s.strip()}

        self.command = args.get('command')
        self.triggered_by = args.get('triggered_by') or args.get('triggered-by')
        self.parent_id = args.get('follow_children') or args.get('follow-children')
        if self.parent_id is not None:
            self.parent_id = int(self.parent_id)

    def match(self, job) -> bool:
        if self.statuses and job.status not in self.statuses:
            return False
        if self.command and self.command not in (job.command or ''):
            return False
        if self.triggered_by and self.triggered_by not in (job.triggered_by or ''):
            return False
        if self.parent_id is not None and job.parent_job_id != self.parent_id:
            return False
        return True


# ─────────── Форматтеры ───────────

def _status_color(status):
    return {
        'pending': Color.BRIGHT_YELLOW,
        'running': Color.BRIGHT_CYAN,
        'done': Color.BRIGHT_GREEN,
        'failed': Color.BRIGHT_RED,
        'canceled': Color.BRIGHT_BLACK,
        'timeout': Color.BRIGHT_MAGENTA,
    }.get(status, Color.WHITE)


def _short_args(args):
    if not args:
        return ''
    s = ', '.join(f'{k}={v}' for k, v in args.items())
    return f'({s})' if s else ''


def _fmt_ts(dt=None):
    dt = dt or datetime.now()
    return dt.strftime('%H:%M:%S')


def _print_event(kind: str, job, extra: str = ''):
    ts = console.colored(_fmt_ts(), Color.BRIGHT_BLACK)

    if kind == 'created':
        marker = console.colored('+', Color.BRIGHT_GREEN)
    elif kind == 'updated':
        marker = console.colored('~', Color.BRIGHT_CYAN)
    elif kind == 'removed':
        marker = console.colored('-', Color.BRIGHT_RED)
    else:
        marker = ' '

    status = console.colored(job.status, _status_color(job.status))
    job_id = console.colored(f"#{job.id}", Color.BOLD)
    cmd = job.command or '?'
    args_str = console.dim(_short_args(job.args)) if job.args else ''
    src = console.dim(f"← {job.triggered_by}") if job.triggered_by else ''

    attempts = ''
    if job.attempts:
        attempts = console.dim(f"try {job.attempts}/{job.max_attempts}")

    line = f"{ts} {marker} {job_id:<6} [{status:<9}] {cmd:<28} {args_str}"
    if attempts:
        line += f"  {attempts}"
    if src:
        line += f"  {src}"
    if extra:
        line += f"  {extra}"

    print(line, flush=True)


def _print_jsonl(kind, job, extra=''):
    row = {
        'event': kind,
        'ts': datetime.now().isoformat(),
        'job': {
            'id': job.id,
            'command': job.command,
            'args': job.args,
            'status': job.status,
            'attempts': job.attempts,
            'max_attempts': job.max_attempts,
            'priority': job.priority,
            'triggered_by': job.triggered_by,
            'parent_job_id': job.parent_job_id,
            'exit_code': job.exit_code,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'finished_at': job.finished_at.isoformat() if job.finished_at else None,
            'error': (job.error or '')[:200] if job.error else None,
        },
    }
    if extra:
        row['extra'] = extra
    print(json.dumps(row, ensure_ascii=False), flush=True)


def _print_compact(kind, job, extra=''):
    ts = _fmt_ts()
    status_code = job.status[:4]
    print(f"{ts} {kind[0].upper()} {job.id} {status_code} {job.command}",
          flush=True)


# ─────────── Основной цикл ───────────

def _stream(context, filters: Filters, interval: float, fmt: str):
    from homer.queue import QueueStorage

    storage = QueueStorage(context['config'])

    print_fn = {
        'pretty': _print_event,
        'jsonl': _print_jsonl,
        'compact': _print_compact,
    }.get(fmt, _print_event)

    # Снимок начального состояния
    last: dict[int, dict] = {}
    try:
        initial = storage.list(limit=2000)
    except Exception:
        initial = []

    for job in initial:
        last[job.id] = {
            'status': job.status,
            'attempts': job.attempts,
            'exit_code': job.exit_code,
        }
        if filters.match(job):
            print_fn('created', job, extra='(initial)')

    if fmt == 'pretty':
        console.comment(
            f"─── Начало потока (интервал {interval}с, фильтр: "
            f"{'*' if not filters.statuses else ','.join(filters.statuses)}) ───"
        )

    try:
        while True:
            try:
                jobs = storage.list(limit=2000)
            except Exception as e:
                print(f"[error] {e}", file=sys.stderr, flush=True)
                time.sleep(interval * 2)
                continue

            current_ids = set()
            for job in jobs:
                current_ids.add(job.id)
                prev = last.get(job.id)

                if prev is None:
                    # Новая задача
                    if filters.match(job):
                        print_fn('created', job)
                else:
                    # Изменения
                    changed = (
                        prev['status'] != job.status
                        or prev['attempts'] != job.attempts
                        or prev['exit_code'] != job.exit_code
                    )
                    if changed and filters.match(job):
                        extra = ''
                        if prev['status'] != job.status:
                            extra = f"({prev['status']} → {job.status})"
                        elif prev['attempts'] != job.attempts:
                            extra = f"(attempt {prev['attempts']}→{job.attempts})"
                        print_fn('updated', job, extra=extra)

                last[job.id] = {
                    'status': job.status,
                    'attempts': job.attempts,
                    'exit_code': job.exit_code,
                }

            # Удалённые
            for jid in set(last) - current_ids:
                removed = last.pop(jid)
                if fmt == 'pretty':
                    ts = console.colored(_fmt_ts(), Color.BRIGHT_BLACK)
                    print(f"{ts} {console.colored('-', Color.BRIGHT_RED)} "
                          f"{console.colored(f'#{jid}', Color.BOLD):<6} "
                          f"{console.dim('removed')}", flush=True)
                elif fmt == 'jsonl':
                    print(json.dumps({
                        'event': 'removed',
                        'ts': datetime.now().isoformat(),
                        'job_id': jid,
                    }), flush=True)

            time.sleep(interval)

    except KeyboardInterrupt:
        if fmt == 'pretty':
            print()
            console.comment("─── Поток остановлен ───")
        return 0
    finally:
        storage.close()


def execute(context):
    args = context['args']

    try:
        interval = float(args.get('interval', 1.0))
        if interval < 0.2:
            interval = 0.2
    except (TypeError, ValueError):
        interval = 1.0

    fmt = (args.get('format') or 'pretty').lower()
    if fmt not in ('pretty', 'jsonl', 'compact'):
        console.error("--format должен быть pretty|jsonl|compact")
        return 2

    filters = Filters(args)

    if fmt == 'pretty':
        console.banner(
            "trace:watch",
            "поток событий очереди (Ctrl+C для остановки)",
            color=Color.BRIGHT_CYAN,
        )

    return _stream(context, filters, interval, fmt)
