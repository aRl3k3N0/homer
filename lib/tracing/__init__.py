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
    get_current_span_id,
    get_current_trace_id,
    setup_tracing,
    shutdown_tracing,
    span,
    tracer,
)

__all__ = [
    'get_current_span_id',
    'get_current_trace_id',
    'setup_tracing',
    'shutdown_tracing',
    'span',
    'tracer',
]
