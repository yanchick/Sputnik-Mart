"""Сервис каталога: фильтры, карточка, схема и образец (T074)."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from contracts import Dataset as DatasetContract
from contracts import FileFormat, SchemaField
from observability import ApiError

from . import repository as repo
from .sample import render_sample


def to_contract(dataset: repo.Dataset) -> DatasetContract:
    """Преобразовать ORM-датасет в контрактную Pydantic-модель."""
    return DatasetContract(
        datasetId=dataset.dataset_id,
        providerId=dataset.provider_id,
        name=dataset.name,
        category=dataset.category,
        frequencySec=dataset.frequency_sec,
        volumeEstimate=dataset.volume_estimate,
        pricePerUnit=float(dataset.price_per_unit),
        qualityScore=float(dataset.quality_score),
        lastUpdatedAt=dataset.last_updated_at,
        licence=dataset.licence,
    )


def to_schema_field(field: repo.DatasetField) -> SchemaField:
    """Преобразовать ORM-поле в контрактное описание схемы."""
    return SchemaField(
        name=field.name,
        type=field.type,
        unit=field.unit,
        nullable=field.nullable,
        ordinal=field.ordinal,
    )


async def list_datasets(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    category: str | None,
    min_quality: float | None,
    sort_by: str,
) -> tuple[list[DatasetContract], int]:
    """Список датасетов с фильтрами и пагинацией."""
    datasets, total = await repo.list_datasets(
        session,
        page=page,
        page_size=page_size,
        category=category,
        min_quality=min_quality,
        sort_by=sort_by,
    )
    return [to_contract(dataset) for dataset in datasets], total


async def get_dataset(session: AsyncSession, dataset_id: str) -> DatasetContract:
    """Карточка датасета или 404."""
    dataset = await repo.get_dataset(session, dataset_id)
    if dataset is None:
        raise ApiError(404, "NOT_FOUND", "Датасет не найден")
    return to_contract(dataset)


async def get_schema(session: AsyncSession, dataset_id: str) -> list[SchemaField]:
    """Схема полей датасета или 404."""
    dataset = await repo.get_dataset(session, dataset_id)
    if dataset is None:
        raise ApiError(404, "NOT_FOUND", "Датасет не найден")
    return [to_schema_field(field) for field in await repo.get_fields(session, dataset_id)]


async def get_sample(session: AsyncSession, dataset_id: str, fmt: FileFormat) -> tuple[bytes, str]:
    """Образец датасета в выбранном формате или 404."""
    dataset = await repo.get_dataset(session, dataset_id)
    if dataset is None:
        raise ApiError(404, "NOT_FOUND", "Датасет не найден")
    fields = await repo.get_fields(session, dataset_id)
    return render_sample(dataset, fields, fmt)


async def update_quality_scores(session: AsyncSession, scores: Mapping[str, float]) -> list[str]:
    """Обновить ``qualityScore`` каталога по данным quality-service (M6)."""
    return await repo.update_quality_scores(session, scores)


__all__ = [
    "get_dataset",
    "get_sample",
    "get_schema",
    "list_datasets",
    "to_contract",
    "to_schema_field",
    "update_quality_scores",
]
