"""Общие схемы контрактов: ошибки, пагинация и формат выгрузки.

Соответствуют переиспользуемым компонентам OpenAPI и описательному конверту
событий: ``Error``, ``ErrorDetail``, ``Pagination``, ``FileFormat``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FileFormat(StrEnum):
    """Поддерживаемые форматы образца и выгрузки (``FileFormat``)."""

    CSV = "CSV"
    JSON = "JSON"
    PARQUET = "PARQUET"


class ErrorDetail(BaseModel):
    """Деталь ошибки для конверта ``{error:{...,details}}`` (``ErrorDetail``)."""

    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    message: str | None = None
    code: str | None = None


class ErrorBody(BaseModel):
    """Тело ошибки с обязательными ``code``/``message`` и сквозным ``requestId``."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    requestId: str | None = None
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    """Единый конверт ошибок ``{error:{code,message,requestId,details}}``."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class Pagination(BaseModel):
    """Метаданные пагинации ``{page,pageSize,total,totalPages,hasMore}``."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    total: int = Field(default=0, ge=0)
    totalPages: int = Field(default=0, ge=0)
    hasMore: bool = False


class PagedResponse[DataT](BaseModel):
    """Обёртка пагинированного ответа ``{data,pagination}`` (``PagedResponse``)."""

    model_config = ConfigDict(extra="forbid")

    data: list[DataT]
    pagination: Pagination
