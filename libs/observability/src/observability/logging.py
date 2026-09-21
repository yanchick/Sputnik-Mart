"""Структурированное JSON-логирование (structlog) со сквозным ``requestId``."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

from .request_id import get_request_id
from .tracing import current_trace_id

_LEVELS = logging.getLevelNamesMapping()


def _inject_request_id(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Добавить ``requestId`` и ``traceId`` в событие, если они есть в контексте."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("requestId", request_id)
    trace_id = current_trace_id()
    if trace_id is not None:
        event_dict.setdefault("traceId", trace_id)
    return event_dict


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Настроить structlog: JSON по умолчанию, консоль для локальной отладки."""
    numeric_level = _LEVELS.get(level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_request_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Вернуть structlog-логгер для указанного имени."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


__all__ = ["configure_logging", "get_logger"]
