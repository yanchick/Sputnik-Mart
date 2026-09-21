"""Unit-тест метрик лага консьюмеров и свежести витрины (T156, FR-026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from quality.metrics import (
    DEFAULT_DEGRADATION_THRESHOLD,
    consumer_lag_seconds,
    data_freshness_seconds,
    evaluate_degradation_alerts,
    publish_consumer_lag,
    publish_data_freshness,
    publish_quality,
    quality_degradation_ratio,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def test_consumer_lag_and_freshness_seconds() -> None:
    assert consumer_lag_seconds(None, now=NOW) == 0.0
    assert consumer_lag_seconds(NOW - timedelta(seconds=30), now=NOW) == pytest.approx(30.0)
    # Будущая метка времени не даёт отрицательный лаг.
    assert consumer_lag_seconds(NOW + timedelta(seconds=10), now=NOW) == 0.0
    assert data_freshness_seconds(NOW - timedelta(minutes=5), now=NOW) == pytest.approx(300.0)


def test_publish_consumer_lag_and_freshness_update_registry() -> None:
    publish_consumer_lag("sensors.readings.v1", 0, NOW - timedelta(seconds=7), now=NOW)
    publish_data_freshness("ds_weather-stations", NOW - timedelta(seconds=45), now=NOW)

    assert REGISTRY.get_sample_value(
        "sputnik_consumer_lag", {"topic": "sensors.readings.v1", "partition": "0"}
    ) == pytest.approx(7.0)
    assert REGISTRY.get_sample_value(
        "sputnik_data_freshness_seconds", {"dataset": "ds_weather-stations"}
    ) == pytest.approx(45.0)


def test_quality_degradation_ratio_is_clamped() -> None:
    assert quality_degradation_ratio(0.9, 0.9) == 0.0
    assert quality_degradation_ratio(1.0, 0.9) == 0.0
    assert quality_degradation_ratio(0.45, 0.9) == pytest.approx(0.5)
    assert quality_degradation_ratio(0.0, 0.9) == pytest.approx(1.0)
    assert quality_degradation_ratio(0.5, 0.0) == 0.0


def test_publish_quality_sets_score_and_degradation() -> None:
    degradation = publish_quality("ds_air-quality", 0.5, baseline=1.0)

    assert degradation == pytest.approx(0.5)
    assert REGISTRY.get_sample_value(
        "sputnik_quality_score", {"dataset": "ds_air-quality"}
    ) == pytest.approx(0.5)
    assert REGISTRY.get_sample_value(
        "sputnik_quality_degradation_ratio", {"dataset": "ds_air-quality"}
    ) == pytest.approx(0.5)


def test_evaluate_degradation_alerts_marks_only_degraded() -> None:
    rows = [
        {"dataset_id": "ds_ok", "quality_score": 0.95},
        {"dataset_id": "ds_bad", "quality_score": 0.4},
    ]
    alerts = evaluate_degradation_alerts(rows, baseline=0.9)

    by_dataset = {alert.dataset: alert for alert in alerts}
    assert by_dataset["ds_ok"].active is False
    assert by_dataset["ds_bad"].active is True
    assert by_dataset["ds_bad"].degradation > DEFAULT_DEGRADATION_THRESHOLD
