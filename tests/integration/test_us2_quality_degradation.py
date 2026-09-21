"""Интеграционный тест деградации и восстановления качества (T109, SC-008)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from sim.dirty import DirtyConfig, contaminate
from sim.sensors import build_stations, generate_readings
from validation.main import run_validation

pytestmark = pytest.mark.integration

DATASET = "ds_weather-stations"


def _clean_readings() -> list[dict[str, Any]]:
    return generate_readings(seed=42, periods=6, stations=build_stations()[:1])


async def _flow(store: Any) -> tuple[float, float, float]:
    clean = _clean_readings()

    _b1, _k1, clean_reports = await run_validation(
        clean, store=store, bucket="lake", dt=date(2026, 9, 1)
    )
    dirty = contaminate(
        clean,
        seed=42,
        config=DirtyConfig(missing=0.3, duplicate=0.3, outlier=0.2, broken=0.2),
    )
    _b2, _k2, dirty_reports = await run_validation(
        dirty, store=store, bucket="lake", dt=date(2026, 9, 2)
    )
    # Очистка: тот же чистый вход после загрязнения -> показатель восстановлен.
    _b3, _k3, recovered_reports = await run_validation(
        clean, store=store, bucket="lake", dt=date(2026, 9, 3)
    )

    clean_score = float(clean_reports[DATASET]["quality_score"])
    dirty_score = float(dirty_reports[DATASET]["quality_score"])
    recovered_score = float(recovered_reports[DATASET]["quality_score"])
    assert dirty_score < clean_score
    assert recovered_score == pytest.approx(clean_score)
    assert dirty_reports[DATASET]["missing_rate"] > 0.0
    assert dirty_reports[DATASET]["dup_rate"] > 0.0
    return clean_score, dirty_score, recovered_score


def test_quality_degrades_then_recovers(minio_store: Any) -> None:
    clean, dirty, recovered = asyncio.run(_flow(minio_store))
    assert clean > dirty
    assert recovered == pytest.approx(clean)
