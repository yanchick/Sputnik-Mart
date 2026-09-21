"""Генератор ``sim-providers``: провайдеры, датасеты и партнёрские CSV (T100)."""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import DatasetCategory

DEFAULT_SEED = 42


@dataclass(frozen=True)
class FieldRecord:
    """Поле схемы датасета."""

    name: str
    type: str
    unit: str | None = None
    nullable: bool = True


@dataclass(frozen=True)
class DatasetRecord:
    """Шаблон датасета каталога."""

    dataset_id: str
    provider_id: str
    name: str
    category: DatasetCategory
    frequency_sec: int
    volume_estimate: str
    price_per_unit: float
    quality_score: float
    licence: str = "sputnik_edu_v1"
    fields: tuple[FieldRecord, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProviderRecord:
    """Провайдер данных."""

    provider_id: str
    name: str
    datasets: tuple[DatasetRecord, ...] = field(default_factory=tuple)


def _weather_fields() -> tuple[FieldRecord, ...]:
    return (
        FieldRecord("temperature", "DOUBLE", "C"),
        FieldRecord("humidity", "DOUBLE", "%"),
        FieldRecord("pressure", "DOUBLE", "hPa"),
        FieldRecord("station", "STRING"),
        FieldRecord("measuredAt", "DATETIME"),
        FieldRecord("geo", "GEO"),
    )


def _air_fields() -> tuple[FieldRecord, ...]:
    return (
        FieldRecord("pm2_5", "DOUBLE", "ug/m3"),
        FieldRecord("pm10", "DOUBLE", "ug/m3"),
        FieldRecord("noise", "DOUBLE", "dBA", nullable=True),
        FieldRecord("station", "STRING"),
        FieldRecord("measuredAt", "DATETIME"),
    )


def _energy_fields() -> tuple[FieldRecord, ...]:
    return (
        FieldRecord("consumption_kwh", "DOUBLE", "kWh"),
        FieldRecord("meterId", "STRING"),
        FieldRecord("isPeak", "BOOLEAN"),
        FieldRecord("measuredAt", "DATETIME"),
    )


def _transport_fields() -> tuple[FieldRecord, ...]:
    return (
        FieldRecord("trafficFlow", "INT", "veh/h"),
        FieldRecord("segment", "STRING"),
        FieldRecord("speed", "DOUBLE", "km/h"),
        FieldRecord("measuredAt", "DATETIME"),
    )


def _commerce_fields() -> tuple[FieldRecord, ...]:
    return (
        FieldRecord("sales", "DOUBLE", "RUB"),
        FieldRecord("orders", "INT"),
        FieldRecord("category", "STRING"),
        FieldRecord("measuredAt", "DATETIME"),
    )


def build_catalog(seed: int = DEFAULT_SEED) -> tuple[ProviderRecord, ...]:
    """Детерминированно собрать провайдеров, датасеты и поля (FR-029)."""
    generator = random.Random(seed)
    definitions: tuple[tuple[str, str, DatasetRecord], ...] = (
        (
            "pv_meteo",
            "Метеослужба",
            DatasetRecord(
                "ds_weather-stations",
                "pv_meteo",
                "Метеостанции города",
                DatasetCategory.WEATHER,
                60,
                "1.2M rows/month",
                round(generator.uniform(500, 2000), 2),
                round(generator.uniform(0.85, 0.98), 3),
                fields=_weather_fields(),
            ),
        ),
        (
            "pv_air",
            "ЭкоМониторинг",
            DatasetRecord(
                "ds_air-quality",
                "pv_air",
                "Качество воздуха",
                DatasetCategory.AIR_QUALITY,
                300,
                "240K rows/month",
                round(generator.uniform(300, 1500), 2),
                round(generator.uniform(0.8, 0.97), 3),
                fields=_air_fields(),
            ),
        ),
        (
            "pv_energy",
            "Горэнерго",
            DatasetRecord(
                "ds_energy-consumption",
                "pv_energy",
                "Потребление энергии",
                DatasetCategory.ENERGY,
                900,
                "90K rows/month",
                round(generator.uniform(700, 2500), 2),
                round(generator.uniform(0.88, 0.99), 3),
                fields=_energy_fields(),
            ),
        ),
        (
            "pv_transport",
            "Транспорт-Данные",
            DatasetRecord(
                "ds_traffic-flow",
                "pv_transport",
                "Транспортный поток",
                DatasetCategory.TRANSPORT,
                120,
                "3.6M rows/month",
                round(generator.uniform(400, 1800), 2),
                round(generator.uniform(0.75, 0.95), 3),
                fields=_transport_fields(),
            ),
        ),
        (
            "pv_market",
            "Маркет-Аналитика",
            DatasetRecord(
                "ds_retail-sales",
                "pv_market",
                "Розничные продажи",
                DatasetCategory.COMMERCE,
                86400,
                "30K rows/month",
                round(generator.uniform(900, 3000), 2),
                round(generator.uniform(0.7, 0.93), 3),
                fields=_commerce_fields(),
            ),
        ),
    )
    grouped: dict[str, list[DatasetRecord]] = {}
    names: dict[str, str] = {}
    for provider_id, provider_name, dataset in definitions:
        grouped.setdefault(provider_id, []).append(dataset)
        names[provider_id] = provider_name
    return tuple(
        ProviderRecord(provider_id, names[provider_id], tuple(datasets))
        for provider_id, datasets in grouped.items()
    )


async def seed_catalog(session: AsyncSession, seed: int = DEFAULT_SEED) -> list[str]:
    """Идемпотентно наполнить ``catalog.*`` готовыми датасетами."""
    dataset_ids: list[str] = []
    for provider in build_catalog(seed):
        await session.execute(
            text("""
                INSERT INTO catalog.providers (provider_id, name, status)
                VALUES (:provider_id, :name, 'ACTIVE')
                ON CONFLICT (provider_id) DO UPDATE SET name = EXCLUDED.name
                """),
            {"provider_id": provider.provider_id, "name": provider.name},
        )
        for dataset in provider.datasets:
            await session.execute(
                text("""
                    INSERT INTO catalog.datasets
                        (dataset_id, provider_id, name, category, frequency_sec,
                         volume_estimate, price_per_unit, quality_score, licence, last_updated_at)
                    VALUES
                        (:dataset_id, :provider_id, :name, :category, :frequency_sec,
                         :volume_estimate, :price_per_unit, :quality_score, :licence, :updated)
                    ON CONFLICT (dataset_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        price_per_unit = EXCLUDED.price_per_unit,
                        quality_score = EXCLUDED.quality_score,
                        last_updated_at = EXCLUDED.last_updated_at
                    """),
                {
                    "dataset_id": dataset.dataset_id,
                    "provider_id": dataset.provider_id,
                    "name": dataset.name,
                    "category": dataset.category.value,
                    "frequency_sec": dataset.frequency_sec,
                    "volume_estimate": dataset.volume_estimate,
                    "price_per_unit": dataset.price_per_unit,
                    "quality_score": dataset.quality_score,
                    "licence": dataset.licence,
                    "updated": datetime.now(UTC),
                },
            )
            for ordinal, schema_field in enumerate(dataset.fields):
                await session.execute(
                    text("""
                        INSERT INTO catalog.dataset_fields
                            (dataset_id, name, ordinal, type, unit, nullable)
                        VALUES
                            (:dataset_id, :name, :ordinal, :type, :unit, :nullable)
                        ON CONFLICT (dataset_id, name) DO UPDATE SET
                            ordinal = EXCLUDED.ordinal,
                            type = EXCLUDED.type,
                            unit = EXCLUDED.unit,
                            nullable = EXCLUDED.nullable
                        """),
                    {
                        "dataset_id": dataset.dataset_id,
                        "name": schema_field.name,
                        "ordinal": ordinal,
                        "type": schema_field.type,
                        "unit": schema_field.unit,
                        "nullable": schema_field.nullable,
                    },
                )
            dataset_ids.append(dataset.dataset_id)
    return dataset_ids


def write_partner_csvs(base_dir: Path, seed: int = DEFAULT_SEED) -> list[Path]:
    """Записать детерминированные партнёрские CSV в ``lake/partner/{provider}/{dt}.csv``."""
    generator = random.Random(seed)
    today = date(2026, 9, 1)
    written: list[Path] = []
    for provider in build_catalog(seed):
        directory = base_dir / "partner" / provider.provider_id
        directory.mkdir(parents=True, exist_ok=True)
        for offset in range(3):
            day = today + timedelta(days=offset)
            path = directory / f"{day.isoformat()}.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["stationId", "metric", "value", "measuredAt"])
                for row_index in range(5):
                    writer.writerow(
                        [
                            f"st_{provider.provider_id}_{row_index}",
                            "TEMPERATURE",
                            round(generator.uniform(-20, 30), 2),
                            datetime(2026, 9, 1, row_index, tzinfo=UTC).isoformat(),
                        ]
                    )
            written.append(path)
    return written


__all__ = [
    "DEFAULT_SEED",
    "DatasetRecord",
    "FieldRecord",
    "ProviderRecord",
    "build_catalog",
    "seed_catalog",
    "write_partner_csvs",
]
