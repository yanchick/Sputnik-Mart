"""Репозитории каталога: ``Provider``, ``Dataset``, ``DatasetField`` (T073)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from db.postgres import Base

SORT_COLUMNS = {"createdAt", "lastUpdatedAt", "pricePerUnit", "qualityScore"}

#: Колонка-ключ сортировки для каждого поддерживаемого ``sortBy`` (FR-003).
SORT_COLUMN_MAP = {
    "qualityScore": "quality_score",
    "pricePerUnit": "price_per_unit",
    "lastUpdatedAt": "last_updated_at",
    "createdAt": "dataset_id",
}


class Provider(Base):
    """Поставщик данных (``catalog.providers``)."""

    __tablename__ = "providers"
    __table_args__ = {"schema": "catalog"}

    provider_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    meta_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class Dataset(Base):
    """Продаваемый датасет (``catalog.datasets``)."""

    __tablename__ = "datasets"
    __table_args__ = {"schema": "catalog"}

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    frequency_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_estimate: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    licence: Mapped[str] = mapped_column(Text, nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class DatasetField(Base):
    """Поле схемы датасета (``catalog.dataset_fields``)."""

    __tablename__ = "dataset_fields"
    __table_args__ = {"schema": "catalog"}

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


def _filter_conditions(category: str | None, min_quality: float | None) -> list[Any]:
    """Собрать условия фильтрации один раз для count- и page-запросов (FR-003)."""
    conditions: list[Any] = []
    if category is not None:
        conditions.append(Dataset.category == category)
    if min_quality is not None:
        conditions.append(Dataset.quality_score >= Decimal(str(min_quality)))
    return conditions


def _order_column(sort_by: str) -> Any:
    """Разрешить ``sortBy`` в колонку ORM с детерминированным тай-брейком."""
    attr = SORT_COLUMN_MAP.get(sort_by, SORT_COLUMN_MAP["createdAt"])
    return getattr(Dataset, attr)


async def list_datasets(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    category: str | None = None,
    min_quality: float | None = None,
    sort_by: str = "createdAt",
) -> tuple[list[Dataset], int]:
    """Постранично вернуть датасеты с фильтрами ``category``/``minQuality``.

    Общее число строк считается оконной функцией в том же запросе, что и
    страница (один обход вместо двух), а при пустой странице число берётся
    отдельным ``COUNT`` — результат всегда согласован.
    """
    conditions = _filter_conditions(category, min_quality)
    order_column = _order_column(sort_by)
    total_over = func.count().over().label("total_rows")
    statement = (
        select(Dataset, total_over)
        .where(*conditions)
        .order_by(order_column, Dataset.dataset_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(statement)).all()
    if rows:
        return [row[0] for row in rows], int(rows[0][1])

    count_statement = select(func.count()).select_from(Dataset).where(*conditions)
    total = int((await session.execute(count_statement)).scalar_one())
    return [], total


async def get_dataset(session: AsyncSession, dataset_id: str) -> Dataset | None:
    """Найти датасет по идентификатору."""
    return await session.get(Dataset, dataset_id)


async def get_fields(session: AsyncSession, dataset_id: str) -> list[DatasetField]:
    """Вернуть поля схемы датасета по порядку."""
    statement = (
        select(DatasetField)
        .where(DatasetField.dataset_id == dataset_id)
        .order_by(DatasetField.ordinal)
    )
    return list((await session.execute(statement)).scalars().all())


async def update_quality_scores(
    session: AsyncSession,
    scores: Mapping[str, float],
    *,
    updated_at: datetime | None = None,
) -> list[str]:
    """Обновить ``quality_score`` датасетов идемпотентным upsert по ключу (M6).

    Возвращаются все переданные ``datasetId`` (как и раньше — без проверки
    существования): отсутствующий датасет просто не меняет строк.
    """
    if not scores:
        return []
    moment = updated_at or datetime.now(UTC)
    for dataset_id, score in scores.items():
        await session.execute(
            text(
                "UPDATE catalog.datasets "
                "SET quality_score = :score, last_updated_at = :updated "
                "WHERE dataset_id = :dataset_id"
            ),
            {"score": float(score), "updated": moment, "dataset_id": dataset_id},
        )
    return list(scores)


__all__ = [
    "SORT_COLUMNS",
    "Dataset",
    "DatasetField",
    "Provider",
    "get_dataset",
    "get_fields",
    "list_datasets",
    "update_quality_scores",
]
