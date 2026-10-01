"""
Реализация метрик Homer.

Метрики:
    homer_queue_jobs_total{status}              — счётчик по статусам
    homer_queue_jobs_in_progress                — gauge текущих задач
    homer_queue_job_duration_seconds            — histogram длительностей
    homer_job_attempts                          — histogram попыток
    homer_command_executions_total{command,status}
    homer_command_duration_seconds{command}     — histogram
    homer_scheduler_ticks_total
    homer_scheduler_last_tick_timestamp         — gauge (unixtime)
    homer_notifications_total{provider,status}
    homer_db_queries_total{driver,op}
    homer_errors_total{source}
"""
from __future__ import annotations

import time
import logging

_log = logging.getLogger('homer.metrics')

try:
    from prometheus_client import (
        Counter, Gauge, Histogram, CollectorRegistry,
        generate_latest, CONTENT_TYPE_LATEST, start_http_server,
    )
    _HAS_PROM = True
except ImportError:
    _HAS_PROM = False
    Counter = Gauge = Histogram = CollectorRegistry = None
    generate_latest = CONTENT_TYPE_LATEST = start_http_server = None


class _Noop:
    """Заглушка для окружений без prometheus_client."""
    def labels(self, *_, **__): return self
    def inc(self, *_, **__): pass
    def set(self, *_, **__): pass
    def observe(self, *_, **__): pass
    def time(self):
        class _T:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return _T()


class MetricsRegistry:
    def __init__(self):
        if not _HAS_PROM:
            self.jobs_total = _Noop()
            self.jobs_in_progress = _Noop()
            self.job_duration = _Noop()
            self.job_attempts = _Noop()
            self.command_exec = _Noop()
            self.command_duration = _Noop()
            self.scheduler_ticks = _Noop()
            self.scheduler_last_tick = _Noop()
            self.notifications = _Noop()
            self.db_queries = _Noop()
            self.errors = _Noop()
            self.registry = None
            return

        self.registry = CollectorRegistry()

        self.jobs_total = Counter(
            'homer_queue_jobs_total',
            'Всего задач, разбитых по статусу',
            ['status'],
            registry=self.registry,
        )
        self.jobs_in_progress = Gauge(
            'homer_queue_jobs_in_progress',
            'Задач сейчас выполняется',
            registry=self.registry,
        )
        self.job_duration = Histogram(
            'homer_queue_job_duration_seconds',
            'Длительность выполнения задач (от started_at до finished_at)',
            buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
            registry=self.registry,
        )
        self.job_attempts = Histogram(
            'homer_job_attempts',
            'Распределение числа попыток для завершённых задач',
            buckets=(1, 2, 3, 5, 10, 20),
            registry=self.registry,
        )
        self.command_exec = Counter(
            'homer_command_executions_total',
            'Запусков команд по статусам',
            ['command', 'status'],
            registry=self.registry,
        )
        self.command_duration = Histogram(
            'homer_command_duration_seconds',
            'Длительность команд',
            ['command'],
            buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 300, 900, 3600),
            registry=self.registry,
        )
        self.scheduler_ticks = Counter(
            'homer_scheduler_ticks_total',
            'Количество tick()-вызовов',
            registry=self.registry,
        )
        self.scheduler_last_tick = Gauge(
            'homer_scheduler_last_tick_timestamp',
            'Время последнего tick() (unixtime)',
            registry=self.registry,
        )
        self.notifications = Counter(
            'homer_notifications_total',
            'Отправленных уведомлений',
            ['provider', 'status'],
            registry=self.registry,
        )
        self.db_queries = Counter(
            'homer_db_queries_total',
            'SQL-запросов через драйверы Homer',
            ['driver', 'op'],
            registry=self.registry,
        )
        self.errors = Counter(
            'homer_errors_total',
            'Ошибок по источникам',
            ['source'],
            registry=self.registry,
        )


_REGISTRY: MetricsRegistry | None = None


def get_metrics() -> MetricsRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = MetricsRegistry()
    return _REGISTRY


# ─────────── Удобные функции ───────────

def observe_job(job, status: str | None = None, duration: float | None = None):
    """Зафиксировать метрики по завершённому job-у."""
    m = get_metrics()
    status = status or job.status

    m.jobs_total.labels(status=status).inc()

    if duration is None and job.finished_at and job.started_at:
        duration = (job.finished_at - job.started_at).total_seconds()
    if duration is not None and duration >= 0:
        m.job_duration.observe(duration)

    if status in ('done', 'failed', 'timeout', 'canceled'):
        m.job_attempts.observe(job.attempts)


def observe_command(command: str, status: str, duration: float):
    m = get_metrics()
    m.command_exec.labels(command=command, status=status).inc()
    m.command_duration.labels(command=command).observe(duration)


def inc_notify(provider: str, status: str = 'ok'):
    get_metrics().notifications.labels(provider=provider, status=status).inc()


def inc_db_query(driver: str, op: str = 'execute'):
    get_metrics().db_queries.labels(driver=driver, op=op).inc()


def inc_error(source: str = 'generic'):
    get_metrics().errors.labels(source=source).inc()


def metrics_endpoint():
    """Возвращает (body_bytes, content_type) для /metrics."""
    if not _HAS_PROM:
        return b"# prometheus_client not installed\n", "text/plain"
    return generate_latest(get_metrics().registry), CONTENT_TYPE_LATEST


def setup_metrics_server(port: int = 9101, addr: str = '0.0.0.0'):
    """Запустить отдельный HTTP-сервер Prometheus на порту."""
    if not _HAS_PROM:
        _log.warning("prometheus_client не установлен — сервер метрик не запущен")
        return
    start_http_server(port, addr=addr)
    _log.info(f"Metrics server: http://{addr}:{port}/metrics")
    print(f"📊 Metrics: http://{addr}:{port}/metrics")
