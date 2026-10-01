"""
Метрики Homer в формате Prometheus.

Использует prometheus_client. Если библиотеки нет — no-op заглушка,
чтобы код работал без обязательной зависимости.
"""
from .metrics import (
    get_metrics, observe_job, observe_command, inc_notify,
    setup_metrics_server, metrics_endpoint, inc_error, inc_db_query,
)

__all__ = [
    'get_metrics', 'observe_job', 'observe_command',
    'inc_notify', 'setup_metrics_server', 'metrics_endpoint',
    'inc_error', 'inc_db_query',
]
