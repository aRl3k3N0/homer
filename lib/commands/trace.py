"""
trace:job — пошаговая трассировка выполнения задачи.

Показывает:
    - дерево спанов из Jaeger/Tempo (если настроен OTLP/Jaeger);
    - fallback: локальный timeline из БД (created_at → started_at →
      finished_at) с попытками и ошибками.
"""
from datetime import datetime

from lib.console import console, Color

DESCRIPTION = "Пошаговая трассировка выполнения job-а"


# ─────────── Сбор данных ───────────

def _load_job(context, job_id):
    from lib.queue import QueueStorage
    storage = QueueStorage(context['config'])
    try:
        return storage.get(job_id)
    finally:
        storage.close()


def _load_children(context, job_id, depth=0, max_depth=5, seen=None):
    """Рекурсивно тянет дочерние задачи."""
    if seen is None:
        seen = set()
    if job_id in seen or depth > max_depth:
        return []
    seen.add(job_id)

    from lib.queue import QueueStorage
    storage = QueueStorage(context['config'])
    try:
        all_jobs = storage.list(limit=1000)
    finally:
        storage.close()

    children = [j for j in all_jobs if j.parent_job_id == job_id]
    result = []
    for c in children:
        result.append(c)
        result.extend(_load_children(context, c.id, depth + 1, max_depth, seen))
    return result


def _fmt_dt(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if dt else '—'


def _delta(a, b):
    if not a or not b:
        return None
    return (b - a).total_seconds()


def _status_color(status):
    return {
        'pending': Color.BRIGHT_YELLOW,
        'running': Color.BRIGHT_CYAN,
        'done': Color.BRIGHT_GREEN,
        'failed': Color.BRIGHT_RED,
        'canceled': Color.BRIGHT_BLACK,
        'timeout': Color.BRIGHT_MAGENTA,
    }.get(status, Color.WHITE)


# ─────────── Timeline из БД ───────────

def _render_db_timeline(job, children):
    console.section("Timeline (из БД)")

    events = []

    events.append(('created', job.created_at, 'задача создана'))
    if job.run_at:
        events.append(('run_at', job.run_at, 'не раньше этого времени'))
    if job.started_at:
        events.append(('started', job.started_at, 'старт выполнения'))
    if job.finished_at:
        events.append(('finished', job.finished_at,
                       f'завершено: {job.status}'))

    for c in children:
        events.append(('child.created', c.created_at,
                       f'родился job #{c.id} ({c.command})'))
        if c.started_at:
            events.append(('child.started', c.started_at,
                           f'job #{c.id} стартовал'))
        if c.finished_at:
            events.append(('child.finished', c.finished_at,
                           f'job #{c.id} → {c.status}'))

    events = [e for e in events if e[1] is not None]
    events.sort(key=lambda x: x[1])

    if not events:
        console.warning("Нет событий для отображения")
        return

    base = events[0][1]

    rows = []
    for kind, dt, msg in events:
        rel = _delta(base, dt)
        rows.append([
            f"+{rel:>8.3f}s",
            dt.strftime('%H:%M:%S.%f')[:-3],
            kind,
            msg,
        ])

    console.table(
        headers=['Δt', 'Время', 'Событие', 'Описание'],
        rows=rows,
        align=['r', 'l', 'l', 'l'],
    )

    # Итоги
    if job.started_at and job.finished_at:
        dur = _delta(job.started_at, job.finished_at)
        console.key_value('Длительность', f"{dur:.3f}s")
    if job.attempts > 1:
        console.key_value('Попыток', f"{job.attempts}/{job.max_attempts}")


# ─────────── Jaeger/Tempo ───────────

def _fetch_traces_from_tempo(context, job_id):
    """
    Пытается получить трейсы из Tempo/Jaeger по тегу job.id.
    Возвращает list[dict] или [].
    """
    cfg = context['config'].get('tracing', {}) or {}
    if not cfg.get('enabled'):
        return []

    exporter = (cfg.get('exporter') or '').lower()
    endpoint = cfg.get('endpoint') or ''

    try:
        import requests
    except ImportError:
        return []

    # Tempo HTTP API
    if 'tempo' in endpoint or ':3200' in endpoint or exporter == 'otlp':
        base = endpoint.replace(':4317', ':3200').rstrip('/')
        url = f"{base}/api/search"
        try:
            r = requests.get(
                url,
                params={
                    'tags': f'job.id={job_id}',
                    'limit': 100,
                },
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get('traces', [])
        except Exception:
            return []

    # Jaeger HTTP API
    if exporter == 'jaeger':
        host = cfg.get('jaeger_host', 'localhost')
        port = cfg.get('jaeger_query_port', 16686)
        url = f"http://{host}:{port}/api/traces"
        try:
            r = requests.get(url, params={'tag': f'job.id:{job_id}', 'limit': 20},
                             timeout=10)
            if r.status_code == 200:
                return r.json().get('data', [])
        except Exception:
            return []

    return []


def _render_tempo_traces(traces):
    if not traces:
        return False

    console.section("Traces (Tempo / Jaeger)")
    for t in traces:
        trace_id = t.get('traceID') or t.get('traceId') or '?'
        spans = t.get('spans') or []
        duration_ms = t.get('durationMs') or (t.get('duration', 0) / 1000)

        console.key_value('Trace ID', trace_id)
        console.key_value('Duration', f"{duration_ms:.1f} ms")
        console.key_value('Spans', len(spans))

        rows = []
        for sp in spans:
            name = sp.get('operationName') or sp.get('name') or '?'
            start = sp.get('startTime') or sp.get('start') or 0
            dur_us = sp.get('duration') or 0
            tags = sp.get('tags') or []
            tag_map = {tag.get('key'): tag.get('value') for tag in tags}
            attrs = tag_map if tag_map else (sp.get('attributes') or {})
            rows.append([
                name[:60],
                f"{start}",
                f"{dur_us/1000:.1f} ms",
                attrs.get('db.system') or attrs.get('notify.provider')
                or attrs.get('job.status') or '',
            ])

        console.table(
            headers=['Span', 'Start (µs)', 'Длительность', 'Атрибут'],
            rows=rows,
            align=['l', 'r', 'r', 'l'],
        )
        console.newline()

    return True


# ─────────── Main ───────────

def execute(context):
    args = context['args']
    job_id = args.get('id') or args.get('_positional', [None])[0]

    if not job_id:
        console.error("Использование: homer trace:job --id=<job_id>")
        return 1

    try:
        job_id = int(job_id)
    except ValueError:
        console.error("job_id должен быть числом")
        return 1

    job = _load_job(context, job_id)
    if not job:
        console.error(f"Job #{job_id} не найден")
        return 1

    children = _load_children(context, job_id)

    # Заголовок
    console.banner(
        f"Trace: job #{job.id}",
        f"{job.command} — {job.status}",
        color=_status_color(job.status),
    )

    console.section("Сводка")
    console.key_value('Команда', job.command)
    console.key_value('Аргументы', str(job.args))
    console.key_value('Статус',
                      console.colored(job.status, _status_color(job.status)))
    console.key_value('Приоритет', job.priority)
    console.key_value('Попыток', f"{job.attempts}/{job.max_attempts}")
    console.key_value('Exit code',
                      job.exit_code if job.exit_code is not None else '—')
    console.key_value('Источник', job.triggered_by or '—')
    if job.parent_job_id:
        console.key_value('Родитель', f"#{job.parent_job_id}")
    console.key_value('Создана', _fmt_dt(job.created_at))
    if job.run_at:
        console.key_value('Не раньше', _fmt_dt(job.run_at))
    console.key_value('Запущена', _fmt_dt(job.started_at))
    console.key_value('Завершена', _fmt_dt(job.finished_at))

    # Timeline из БД
    _render_db_timeline(job, children)

    # Traces из Tempo/Jaeger
    traces = _fetch_traces_from_tempo(context, job_id)
    if not _render_tempo_traces(traces):
        console.section("Traces")
        console.comment(
            "  Traces недоступны. Включите tracing в config.yml и убедитесь, "
            "что Tempo/Jaeger доступен."
        )

    # Ошибка
    if job.error:
        console.section("Ошибка")
        console.colored(job.error, Color.BRIGHT_RED)

    # Результат
    if job.result:
        console.section("Вывод")
        print(job.result[:5000])
        if len(job.result) > 5000:
            console.comment(f"... [ещё {len(job.result) - 5000} символов]")

    # Дети (сводка)
    if children:
        console.section(f"Дочерние задачи ({len(children)})")
        rows = [
            [
                f"#{c.id}",
                c.command,
                console.colored(c.status, _status_color(c.status)),
                _fmt_dt(c.started_at),
                _fmt_dt(c.finished_at),
            ]
            for c in children
        ]
        console.table(
            headers=['ID', 'Команда', 'Статус', 'Запущена', 'Завершена'],
            rows=rows,
            align=['r', 'l', 'c', 'l', 'l'],
        )

    return 0
