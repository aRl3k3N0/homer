"""
Настройка OpenTelemetry.
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Optional

_log = logging.getLogger('homer.tracing')

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.trace import SpanKind, Status, StatusCode
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False
    trace = None


_provider: Optional[Any] = None
_tracer: Optional[Any] = None
_enabled = False


def setup_tracing(config, service_name: str = 'homer') -> bool:
    """
    Инициализирует OpenTelemetry.

    Конфиг (tracing):
        enabled: true
        service_name: homer
        exporter: otlp | jaeger | console | none
        endpoint: "http://localhost:4317"     # OTLP gRPC
        jaeger_endpoint: "http://localhost:14268/api/traces"
        sample_ratio: 1.0                     # 1.0 = всё, 0.1 = 10%
        console: false                        # дублировать спаны в stdout
    """
    global _provider, _tracer, _enabled

    cfg = (config.get('tracing', {}) or {}) if config else {}
    if not cfg.get('enabled', False):
        _log.info('Трассировка выключена')
        return False

    if not _HAS_OTEL:
        _log.warning(
            "opentelemetry не установлен — трассировка выключена. "
            "Установите: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp"
        )
        return False

    service_name = cfg.get('service_name', service_name)
    environment = cfg.get('environment', os.environ.get('ENV', 'dev'))

    resource = Resource.create({
        'service.name': service_name,
        'service.version': config.get('app.version', '1.0.0'),
        'deployment.environment': environment,
    })

    # Семплер
    ratio = float(cfg.get('sample_ratio', 1.0))
    if ratio >= 1.0:
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON
        sampler = ALWAYS_ON
    elif ratio <= 0.0:
        from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
        sampler = ALWAYS_OFF
    else:
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        sampler = TraceIdRatioBased(ratio)

    provider = TracerProvider(resource=resource, sampler=sampler)

    # Экспортёры
    exporters = []

    exporter_name = (cfg.get('exporter') or 'otlp').lower()
    endpoint = cfg.get('endpoint')

    if exporter_name == 'otlp':
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporters.append(OTLPSpanExporter(endpoint=endpoint or 'localhost:4317'))
        except ImportError:
            _log.warning("OTLP exporter не установлен")

    elif exporter_name == 'jaeger':
        try:
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            exporters.append(JaegerExporter(
                agent_host_name=cfg.get('jaeger_host', 'localhost'),
                agent_port=cfg.get('jaeger_port', 6831),
            ))
        except ImportError:
            _log.warning("Jaeger exporter не установлен")

    elif exporter_name == 'zipkin':
        try:
            from opentelemetry.exporter.zipkin.json import ZipkinExporter
            exporters.append(ZipkinExporter(
                endpoint=cfg.get('zipkin_endpoint', 'http://localhost:9411/api/v2/spans'),
            ))
        except ImportError:
            _log.warning("Zipkin exporter не установлен")

    # Опционально — дублирование в консоль
    if cfg.get('console', False):
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        exporters.append(ConsoleSpanExporter())

    for exp in exporters:
        provider.add_span_processor(BatchSpanProcessor(exp))

    trace.set_tracer_provider(provider)

    _provider = provider
    _tracer = trace.get_tracer(service_name)
    _enabled = True

    _log.info(f"Трассировка включена: exporter={exporter_name}, "
              f"endpoint={endpoint}, service={service_name}")
    return True


def shutdown_tracing():
    global _enabled
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception as e:
            _log.warning(f"shutdown_tracing: {e}")
    _enabled = False


# ─────────── Основной API ───────────

@contextlib.contextmanager
def span(name: str, *, kind: str = 'internal', attributes: Optional[dict] = None,
         record_exception: bool = True):
    """
    Контекстный менеджер для спана.

    with span('job.run', attributes={'job_id': 42}):
        do_work()
    """
    if not _enabled or _tracer is None:
        # no-op
        yield None
        return

    kinds = {
        'internal': SpanKind.INTERNAL,
        'server': SpanKind.SERVER,
        'client': SpanKind.CLIENT,
        'producer': SpanKind.PRODUCER,
        'consumer': SpanKind.CONSUMER,
    }

    with _tracer.start_as_current_span(
        name,
        kind=kinds.get(kind, SpanKind.INTERNAL),
        attributes=_clean_attrs(attributes or {}),
    ) as sp:
        try:
            yield sp
            sp.set_status(Status(StatusCode.OK))
        except Exception as e:
            sp.set_status(Status(StatusCode.ERROR, str(e)))
            if record_exception:
                sp.record_exception(e)
            raise


def _clean_attrs(attrs: dict) -> dict:
    """Приводит значения к типам, которые понимает OTel."""
    cleaned = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        elif isinstance(v, (list, tuple)) and all(
            isinstance(x, (str, int, float, bool)) for x in v
        ):
            cleaned[k] = list(v)
        else:
            cleaned[k] = str(v)
    return cleaned


def tracer():
    """Возвращает текущий tracer (или None)."""
    return _tracer


def is_enabled() -> bool:
    return _enabled


def get_current_trace_id() -> Optional[str]:
    if not _enabled or trace is None:
        return None
    sp = trace.get_current_span()
    ctx = sp.get_span_context() if sp else None
    if ctx and ctx.trace_id:
        return format(ctx.trace_id, '032x')
    return None


def get_current_span_id() -> Optional[str]:
    if not _enabled or trace is None:
        return None
    sp = trace.get_current_span()
    ctx = sp.get_span_context() if sp else None
    if ctx and ctx.span_id:
        return format(ctx.span_id, '016x')
    return None
