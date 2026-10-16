"""
Метрики Homer в формате Prometheus.

Использует prometheus_client. Если библиотеки нет — no-op заглушка,
чтобы код работал без обязательной зависимости.
"""

from .metrics import (
    get_metrics,
    inc_db_query,
    inc_error,
    inc_notify,
    metrics_endpoint,
    observe_command,
    observe_job,
    setup_metrics_server,
)

__all__ = [
    'get_metrics',
    'inc_db_query',
    'inc_error',
    'inc_notify',
    'metrics_endpoint',
    'observe_command',
    'observe_job',
    'setup_metrics_server',
]
