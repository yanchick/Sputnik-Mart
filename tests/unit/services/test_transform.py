"""Unit-тесты transform: gold-витрины, прогноз, тональность (T105)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from transform.gold_quality import build_quality_rows
from transform.gold_readings import build_fact_rows, forecast_series, hourly_aggregates
from transform.gold_sentiment import build_sentiment_rows, score_text
from validation.validator import clean_readings

pytestmark = pytest.mark.unit

BASE = datetime(2026, 9, 1, tzinfo=UTC)


def _silver_frame(count: int = 6) -> Any:
    records = [
        {
            "readingId": f"rd_{index}",
            "stationId": "st_meteo-01",
            "providerId": "pv_meteo",
            "metric": "TEMPERATURE",
            "value": 10.0 + index,
            "unit": "C",
            "geo": {"lat": 59.9, "lon": 30.3},
            "measuredAt": (BASE + timedelta(hours=index)).isoformat(),
            "receivedAt": (BASE + timedelta(hours=index, seconds=1)).isoformat(),
        }
        for index in range(count)
    ]
    return clean_readings(records).frame


def test_build_fact_rows_matches_silver() -> None:
    frame = _silver_frame()
    rows = build_fact_rows(frame)
    assert len(rows) == 6
    assert rows[0][0] == "rd_0"
    assert rows[0][3] == "TEMPERATURE"
    assert rows[0][10] == BASE.date()


def test_hourly_aggregates_group_by_station_metric_hour() -> None:
    frame = _silver_frame()
    aggregates = hourly_aggregates(frame)
    assert list(aggregates.columns) == [
        "station_id",
        "metric",
        "hour",
        "readings",
        "avg_value",
        "min_value",
        "max_value",
    ]
    assert aggregates["readings"].sum() == 6


def test_forecast_is_deterministic_and_has_horizon() -> None:
    frame = _silver_frame()
    first = forecast_series(frame, horizon_hours=3)
    second = forecast_series(frame, horizon_hours=3)
    assert first == second
    assert len(first) == 3
    assert {"station_id", "metric", "hour", "forecast_value"} <= set(first[0])
    assert forecast_series(frame.iloc[0:0]) == []


def test_sentiment_scoring_and_aggregation() -> None:
    assert score_text("Отличные данные, рекомендую") > 0
    assert score_text("Ужасное качество, ошибки") < 0
    assert score_text(None) == 0.0
    rows = build_sentiment_rows(
        [
            {
                "reviewId": "rv_1",
                "datasetId": "ds_x",
                "rating": 5,
                "text": "good useful",
                "at": BASE.isoformat(),
            },
            {
                "reviewId": "rv_2",
                "datasetId": "ds_x",
                "rating": 1,
                "text": "bad error",
                "at": BASE.isoformat(),
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0][0] == BASE.date()
    assert rows[0][2] == 2
    assert rows[0][3] == pytest.approx(3.0)
    assert rows[0][5] == 1 and rows[0][6] == 1


def test_quality_rows_from_reports() -> None:
    reports = {
        "ds_x": {
            "dt": "2026-09-01",
            "quality_score": 0.9,
            "missing_rate": 0.0,
            "dup_rate": 0.0,
            "outlier_rate": 0.1,
            "anomalies_cnt": 2,
        }
    }
    rows = build_quality_rows(reports)
    assert rows[0][1] == "ds_x"
    assert rows[0][2] == pytest.approx(0.9)
    assert rows[0][6] == 2
