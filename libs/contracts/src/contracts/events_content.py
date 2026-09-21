"""События контента (датчиков) из ``asyncapi-content.yaml``.

Валидные чтения ``sensors.readings.v1`` и битые записи ``sensors.readings.dlq``.
Инвариант: ``receivedAt`` проставляет только sensor-gateway.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContentTopic(StrEnum):
    """Имена топиков контент-нити."""

    READINGS = "sensors.readings.v1"
    DLQ = "sensors.readings.dlq"


class Metric(StrEnum):
    """Поддерживаемые метрики датчиков (``Metric``)."""

    TEMPERATURE = "TEMPERATURE"
    HUMIDITY = "HUMIDITY"
    PRESSURE = "PRESSURE"
    PM2_5 = "PM2_5"
    PM10 = "PM10"
    NOISE = "NOISE"
    ENERGY_KWH = "ENERGY_KWH"
    TRAFFIC_FLOW = "TRAFFIC_FLOW"


#: Физически допустимые границы значений по метрике (``min``, ``max``).
#: Единый источник истины для sensor-gateway и validation (FR-012, FR-017).
METRIC_RANGES: dict[Metric, tuple[float, float]] = {
    Metric.TEMPERATURE: (-90.0, 60.0),
    Metric.HUMIDITY: (0.0, 100.0),
    Metric.PRESSURE: (300.0, 1100.0),
    Metric.PM2_5: (0.0, 1000.0),
    Metric.PM10: (0.0, 2000.0),
    Metric.NOISE: (0.0, 200.0),
    Metric.ENERGY_KWH: (0.0, 1_000_000_000.0),
    Metric.TRAFFIC_FLOW: (0.0, 10_000_000.0),
}


def metric_bounds(metric: Metric) -> tuple[float, float]:
    """Вернуть допустимый диапазон значения для метрики."""
    return METRIC_RANGES[metric]


#: Соответствие метрики продаваемому датасету (маршрутизация silver).
METRIC_DATASETS: dict[Metric, str] = {
    Metric.TEMPERATURE: "ds_weather-stations",
    Metric.HUMIDITY: "ds_weather-stations",
    Metric.PRESSURE: "ds_weather-stations",
    Metric.PM2_5: "ds_air-quality",
    Metric.PM10: "ds_air-quality",
    Metric.NOISE: "ds_air-quality",
    Metric.ENERGY_KWH: "ds_energy-consumption",
    Metric.TRAFFIC_FLOW: "ds_traffic-flow",
}


def dataset_for_metric(metric: Metric) -> str:
    """Вернуть датасет, к которому относится метрика."""
    return METRIC_DATASETS[metric]


class DeadReadingReason(StrEnum):
    """Причины попадания чтения в DLQ (``DeadReading.reason``)."""

    NULL_VALUE = "NULL_VALUE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    DUPLICATE = "DUPLICATE"


class GeoPoint(BaseModel):
    """Географическая точка измерения (``GeoPoint``)."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class SensorReadingPayload(BaseModel):
    """Валидное показание датчика (``SensorReadingPayload``)."""

    model_config = ConfigDict(extra="forbid")

    readingId: str
    stationId: str
    providerId: str
    metric: Metric
    value: float
    unit: str
    geo: GeoPoint | None = None
    measuredAt: datetime
    receivedAt: datetime


class DeadReadingPayload(BaseModel):
    """Битое показание с причиной отбраковки (``DeadReadingPayload``)."""

    model_config = ConfigDict(extra="forbid")

    readingId: str
    reason: DeadReadingReason
    raw: dict[str, Any] = Field(default_factory=dict)


DeadReading = DeadReadingPayload

__all__ = [
    "METRIC_DATASETS",
    "METRIC_RANGES",
    "ContentTopic",
    "DeadReading",
    "DeadReadingPayload",
    "DeadReadingReason",
    "GeoPoint",
    "Metric",
    "SensorReadingPayload",
    "dataset_for_metric",
    "metric_bounds",
]
