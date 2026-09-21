"""Unit-тесты validation: silver без дублей/пропусков, Pandera (T104)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts import DeadReadingReason
from validation.empty_input import empty_quality_report, empty_silver_frame
from validation.quality_report import report_for_dataset
from validation.validator import SILVER_SCHEMA, clean_readings

pytestmark = pytest.mark.unit

BASE = datetime(2026, 9, 1, tzinfo=UTC)


def _reading(index: int, value: float | None = 10.0, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "readingId": f"rd_{index}",
        "stationId": "st_meteo-01",
        "providerId": "pv_meteo",
        "metric": "TEMPERATURE",
        "value": value,
        "unit": "C",
        "geo": {"lat": 59.9, "lon": 30.3},
        "measuredAt": (BASE + timedelta(hours=index)).isoformat(),
        "receivedAt": (BASE + timedelta(hours=index, seconds=5)).isoformat(),
    }
    record.update(overrides)
    return record


def test_clean_readings_produces_valid_silver() -> None:
    batch = clean_readings([_reading(0, 10.0), _reading(1, 11.0), _reading(2, 12.0)])
    assert batch.quarantine == []
    assert batch.frame.shape[0] == 3
    assert batch.frame["reading_id"].is_unique
    assert not batch.frame["value"].isna().any()
    assert batch.metrics_by_dataset["ds_weather-stations"].quality_score == pytest.approx(1.0)
    SILVER_SCHEMA.validate(batch.frame, lazy=True)


def test_duplicate_is_quarantined_and_not_in_silver() -> None:
    batch = clean_readings([_reading(0, 10.0), _reading(0, 10.0)])
    assert batch.frame.shape[0] == 1
    reasons = {item.reason for item in batch.quarantine}
    assert DeadReadingReason.DUPLICATE in reasons
    metrics = batch.metrics_by_dataset["ds_weather-stations"]
    assert metrics.duplicates == 1


def test_missing_value_is_quarantined() -> None:
    batch = clean_readings([_reading(0, value=None)])
    assert batch.frame.empty
    reasons = {item.reason for item in batch.quarantine}
    assert DeadReadingReason.NULL_VALUE in reasons


def test_outlier_is_flagged_and_clipped() -> None:
    records = [_reading(i, value) for i, value in enumerate([10.0, 11.0, 12.0, 13.0, 1000.0])]
    batch = clean_readings(records)
    assert int(batch.frame["is_outlier"].sum()) == 1
    assert float(batch.frame["value"].max()) < 1000.0
    metrics = batch.metrics_by_dataset["ds_weather-stations"]
    assert metrics.outliers == 1
    assert metrics.outlier_rate > 0.0


def test_gap_is_filled_and_counted() -> None:
    records = [_reading(0, 10.0), _reading(1, 11.0), _reading(3, 13.0)]
    batch = clean_readings(records)
    assert int(batch.frame["is_filled"].sum()) == 1
    assert batch.metrics_by_dataset["ds_weather-stations"].gaps == 1


def test_empty_input_does_not_break_run() -> None:
    batch = clean_readings([])
    assert batch.frame.empty
    assert batch.metrics_by_dataset == {}
    empty_frame = empty_silver_frame()
    assert list(empty_frame.columns) == list(batch.frame.columns)
    report = empty_quality_report("ds_weather-stations", BASE.date())
    assert report["quality_score"] == 1.0
    assert report["anomalies_cnt"] == 0


def test_dirty_batch_scores_lower_and_recovers() -> None:
    dirty = [
        _reading(0, 10.0),
        _reading(0, 10.0),
        _reading(1, value=None),
        _reading(2, 1000.0),
    ]
    baseline = report_for_dataset(
        clean_readings([_reading(i, 10.0) for i in range(4)]).metrics, "ds", BASE.date()
    )
    degraded = report_for_dataset(clean_readings(dirty).metrics, "ds", BASE.date())
    assert degraded["quality_score"] < baseline["quality_score"]
