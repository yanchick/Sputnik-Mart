"""Генератор ``sim.sensors``: детерминированные чтения датчиков (T123).

Погодные, эко-, шумовые и энергетические станции. Ряд = суточная сезонность +
шум + редкие выбросы. Одинаковый ``seed`` даёт идентичную выдачу (FR-029).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_SEED = 42
DEFAULT_INTERVAL_SEC = 3600
DEFAULT_PERIODS = 24
OUTLIER_PROBABILITY = 0.01


@dataclass(frozen=True)
class SensorStation:
    """Определение станции и её метрики."""

    station_id: str
    provider_id: str
    metric: str
    unit: str
    base: float
    amplitude: float
    phase: float
    lat: float
    lon: float


def build_stations() -> tuple[SensorStation, ...]:
    """Вернуть фиксированный набор демонстрационных станций."""
    return (
        SensorStation("st_meteo-01", "pv_meteo", "TEMPERATURE", "C", 10.0, 12.0, 0.0, 59.93, 30.31),
        SensorStation("st_meteo-02", "pv_meteo", "HUMIDITY", "%", 60.0, 20.0, 6.0, 59.94, 30.35),
        SensorStation("st_air-01", "pv_air", "PM2_5", "ug/m3", 35.0, 15.0, 3.0, 59.85, 30.20),
        SensorStation("st_air-02", "pv_air", "NOISE", "dBA", 55.0, 10.0, 8.0, 59.87, 30.25),
        SensorStation(
            "st_energy-01", "pv_energy", "ENERGY_KWH", "kWh", 500.0, 150.0, 12.0, 59.90, 30.30
        ),
        SensorStation(
            "st_traffic-01",
            "pv_transport",
            "TRAFFIC_FLOW",
            "veh/h",
            800.0,
            300.0,
            7.0,
            59.88,
            30.28,
        ),
    )


def _reading_id(station_id: str, index: int, measured_at: datetime) -> str:
    return f"rd_{station_id}_{index:05d}_{int(measured_at.timestamp())}"


def generate_readings(
    *,
    seed: int = DEFAULT_SEED,
    stations: tuple[SensorStation, ...] | None = None,
    interval_sec: int = DEFAULT_INTERVAL_SEC,
    periods: int = DEFAULT_PERIODS,
    start: datetime | None = None,
) -> list[dict[str, Any]]:
    """Сгенерировать чтения: ``periods`` точек на станцию с шагом ``interval_sec``."""
    if periods <= 0:
        return []
    interval = max(1, interval_sec)
    origin = start or datetime(2026, 9, 1, tzinfo=UTC)
    generator = random.Random(seed)
    selected = stations if stations is not None else build_stations()
    readings: list[dict[str, Any]] = []
    for index in range(periods):
        measured_at = origin + timedelta(seconds=interval * index)
        hour = measured_at.hour + measured_at.minute / 60.0
        for station in selected:
            seasonal = station.amplitude * math.sin(2 * math.pi * (hour + station.phase) / 24.0)
            noise = generator.gauss(0.0, station.amplitude * 0.08)
            value = station.base + seasonal + noise
            if generator.random() < OUTLIER_PROBABILITY:
                value *= generator.choice((5.0, 50.0))
            readings.append(
                {
                    "readingId": _reading_id(station.station_id, index, measured_at),
                    "stationId": station.station_id,
                    "providerId": station.provider_id,
                    "metric": station.metric,
                    "value": round(value, 4),
                    "unit": station.unit,
                    "geo": {"lat": station.lat, "lon": station.lon},
                    "measuredAt": measured_at.isoformat(),
                }
            )
    return readings


def readings_digest(readings: list[dict[str, Any]]) -> str:
    """Детерминированный отпечаток выдачи для проверки воспроизводимости."""
    import hashlib
    import json

    payload = json.dumps(readings, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_INTERVAL_SEC",
    "DEFAULT_PERIODS",
    "DEFAULT_SEED",
    "OUTLIER_PROBABILITY",
    "SensorStation",
    "build_stations",
    "generate_readings",
    "readings_digest",
]
