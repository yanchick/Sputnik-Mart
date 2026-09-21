"""OpenTelemetry-трейсинг: тонкая обёртка над API с деградацией до no-op.

SDK подключается опционально через :mod:`importlib`, поэтому библиотека остаётся
импортируемой без установленного экспортёра и в unit-тестах.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer


def configure_tracing(
    service_name: str, *, endpoint: str | None = None, sample_ratio: float = 1.0
) -> None:
    """Настроить глобальный ``TracerProvider``, если установлен OpenTelemetry SDK.

    Без SDK вызов становится безопасным no-op: используется API-трейсер.
    """
    try:
        trace_module = importlib.import_module("opentelemetry.sdk.trace")
        resource_module = importlib.import_module("opentelemetry.sdk.resources")
        export_module = importlib.import_module("opentelemetry.sdk.trace.export")
    except ImportError:
        return

    resource = resource_module.Resource.create({"service.name": service_name})
    provider = trace_module.TracerProvider(resource=resource)
    if endpoint:
        exporter = export_module.OTLPSpanExporter(endpoint=endpoint)
        processor = export_module.BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
    if hasattr(provider, "sampler"):
        sampler_module = importlib.import_module("opentelemetry.sdk.trace.sampling")
        provider.sampler = sampler_module.ParentBased(
            sampler_module.TraceIdRatioBased(sample_ratio)
        )
    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> Tracer:
    """Вернуть трейсер для модуля/сервиса."""
    return trace.get_tracer(name)


@contextmanager
def span(
    tracer: Tracer, name: str, *, attributes: Mapping[str, Any] | None = None
) -> Iterator[Span]:
    """Открыть span с атрибутами и корректно закрыть его при выходе."""
    with tracer.start_as_current_span(name, attributes=dict(attributes or {})) as active:
        yield active


def current_trace_id() -> str | None:
    """Вернуть hex-идентификатор текущего трейса или ``None``."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")


__all__ = ["configure_tracing", "current_trace_id", "get_tracer", "span"]
