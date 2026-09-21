"""Unit-тесты публикации лага/свежести из реальных источников (M3, FR-026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio import AsyncSession

from quality.metrics import evaluate_degradation_alerts, publish_quality
from quality.runtime_metrics import (
    READINGS_PARTITION,
    READINGS_TOPIC,
    dataset_last_updated,
    latest_fact_received_at,
    refresh_runtime_metrics,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.result_rows = rows


class _FakeClickHouse:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.result_rows = rows if rows is not None else [(NOW - timedelta(seconds=30),)]

    async def execute(self, _query: str, _params: Any = None) -> _Rows:
        return _Rows(self.result_rows)


class _Mappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self) -> Any:
        return iter(self._rows)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class _FakeSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, _statement: Any, _params: Any = None) -> _Result:
        return _Result(self._rows)


async def test_latest_fact_received_at_reads_clickhouse() -> None:
    clickhouse = _FakeClickHouse()
    assert await latest_fact_received_at(clickhouse) == NOW - timedelta(seconds=30)
    assert await latest_fact_received_at(_FakeClickHouse(rows=[])) is None


async def test_dataset_last_updated_lists_catalog() -> None:
    session = cast(
        AsyncSession,
        _FakeSession([{"dataset_id": "ds_a", "last_updated_at": NOW - timedelta(seconds=5)}]),
    )
    assert await dataset_last_updated(session) == [("ds_a", NOW - timedelta(seconds=5))]


async def test_refresh_runtime_metrics_sets_gauges_from_inputs() -> None:
    session = cast(
        AsyncSession,
        _FakeSession([{"dataset_id": "ds_metrics", "last_updated_at": NOW - timedelta(seconds=5)}]),
    )
    clickhouse = _FakeClickHouse()

    published = await refresh_runtime_metrics(session, clickhouse, now=NOW)

    assert published[READINGS_TOPIC] == pytest.approx(30.0)
    assert published["ds_metrics"] == pytest.approx(5.0)
    assert REGISTRY.get_sample_value(
        "sputnik_consumer_lag",
        {"topic": READINGS_TOPIC, "partition": str(READINGS_PARTITION)},
    ) == pytest.approx(30.0)
    assert REGISTRY.get_sample_value(
        "sputnik_data_freshness_seconds", {"dataset": "ds_metrics"}
    ) == pytest.approx(5.0)


async def test_refresh_runtime_metrics_empty_fact_is_zero_lag() -> None:
    session = cast(AsyncSession, _FakeSession([]))
    published = await refresh_runtime_metrics(session, _FakeClickHouse(rows=[]), now=NOW)
    assert published[READINGS_TOPIC] == 0.0


def test_alert_threshold_path_is_exercised() -> None:
    publish_quality("ds_lagging", 0.4, baseline=0.9)
    degradation = REGISTRY.get_sample_value(
        "sputnik_quality_degradation_ratio", {"dataset": "ds_lagging"}
    )
    assert degradation is not None and degradation > 0.15

    alerts = evaluate_degradation_alerts([{"dataset_id": "ds_lagging", "quality_score": 0.4}])
    assert alerts[0].active is True
