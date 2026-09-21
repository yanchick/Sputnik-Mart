"""Pydantic v2-модели каталога из ``openapi-catalog.yaml``.

Перечисления и обязательные поля совпадают с контрактом-источником истины;
пагинация и конверт ошибок приходят из :mod:`contracts.common`.
"""

from __future__ import annotations

from datetime import datetime
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

DATASET_ID_PATTERN = r"^ds_[a-z0-9_-]+$"


class DatasetCategory(StrEnum):
    """Категории каталога (``DatasetCategory``)."""

    WEATHER = "WEATHER"
    AIR_QUALITY = "AIR_QUALITY"
    ENERGY = "ENERGY"
    TRANSPORT = "TRANSPORT"
    COMMERCE = "COMMERCE"


class SchemaFieldType(StrEnum):
    """Типы полей схемы датасета (``SchemaField.type``)."""

    STRING = "STRING"
    INT = "INT"
    DOUBLE = "DOUBLE"
    BOOLEAN = "BOOLEAN"
    DATETIME = "DATETIME"
    GEO = "GEO"


class SchemaField(BaseModel):
    """Описание столбца датасета для ``/datasets/{datasetId}/schema``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: SchemaFieldType
    unit: str | None = None
    nullable: bool = True
    ordinal: int | None = None


class QualityScoresUpdate(BaseModel):
    """Внутреннее обновление ``qualityScore`` каталога (M6).

    Вызывается quality-service после пересчёта; тело — карта
    ``datasetId → qualityScore``.
    """

    model_config = ConfigDict(extra="forbid")

    scores: dict[str, float] = Field(default_factory=dict)


class QualityScoresUpdated(BaseModel):
    """Итог обновления ``qualityScore`` каталога."""

    model_config = ConfigDict(extra="forbid")

    updated: list[str]
    count: int


class Dataset(BaseModel):
    """Карточка продукта каталога (``Dataset``)."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str = Field(pattern=DATASET_ID_PATTERN)
    providerId: str
    name: str
    category: DatasetCategory
    frequencySec: int | None = Field(default=None, gt=0)
    volumeEstimate: str | None = None
    pricePerUnit: float = Field(default=0.0, ge=0)
    qualityScore: float = Field(ge=0, le=1)
    lastUpdatedAt: datetime
    licence: str


type PagedDatasets = PagedResponse[Dataset]

__all__ = [
    "DATASET_ID_PATTERN",
    "Dataset",
    "DatasetCategory",
    "ErrorBody",
    "ErrorDetail",
    "ErrorEnvelope",
    "FileFormat",
    "PagedDatasets",
    "PagedResponse",
    "Pagination",
    "QualityScoresUpdate",
    "QualityScoresUpdated",
    "SchemaField",
    "SchemaFieldType",
]
