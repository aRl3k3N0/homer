"""
Трассировка Homer через OpenTelemetry.

Если opentelemetry-* не установлены — все вызовы работают как no-op,
приложение продолжает работать без изменений.

Пример:
    from lib.tracing import tracer, span

    with span('my-op', attributes={'user': 'admin'}):
        ...
"""
from .tracing import (
    setup_tracing,
    shutdown_tracing,
    tracer,
    span,
    get_current_trace_id,
    get_current_span_id,
)

__all__ = [
    'setup_tracing', 'shutdown_tracing',
    'tracer', 'span',
    'get_current_trace_id', 'get_current_span_id',
]
