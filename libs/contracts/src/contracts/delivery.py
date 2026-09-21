"""Pydantic v2-модели доставки из ``openapi-delivery.yaml``.

Включает формат выгрузки, конверт ошибок и константы ответов ``429``
(``Retry-After``) и ``403`` для машинного доступа по ``X-Api-Key``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .common import (
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    FileFormat,
    PagedResponse,
    Pagination,
)

SUBSCRIPTION_ID_PATTERN = r"^sub_[a-z0-9_-]+$"
RETRY_AFTER_HEADER = "Retry-After"
API_KEY_HEADER = "X-Api-Key"
RATE_LIMITED_CODE = "RATE_LIMITED"
FORBIDDEN_CODE = "FORBIDDEN"


class SseEventName(StrEnum):
    """Имена событий живого потока SSE."""

    READING = "reading"
    PING = "ping"


class RetryAfter(BaseModel):
    """Заголовок ``Retry-After`` ответа ``429`` (секунды до повтора)."""

    model_config = ConfigDict(extra="forbid")

    seconds: int = Field(ge=0)


__all__ = [
    "API_KEY_HEADER",
    "FORBIDDEN_CODE",
    "RATE_LIMITED_CODE",
    "RETRY_AFTER_HEADER",
    "SUBSCRIPTION_ID_PATTERN",
    "ErrorBody",
    "ErrorDetail",
    "ErrorEnvelope",
    "FileFormat",
    "PagedResponse",
    "Pagination",
    "RetryAfter",
    "SseEventName",
]
