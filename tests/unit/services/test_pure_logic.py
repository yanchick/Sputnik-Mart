"""Unit-тесты чистой логики US2/US3, не требующей БД (переходы, отчёты, витрины).

Покрывают семантику статусов подписки, сборку отчёта качества и идемпотентную
загрузку gold-витрин — эти ветки не покрываются контрактными/e2e тестами.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest
from order.subscription_states import (
    SubscriptionAction,
    SubscriptionStateError,
    apply_transition,
    is_streaming,
    is_terminal,
    next_status,
)

from catalog import service as catalog_service
from contracts import FileFormat
from observability import ApiError
from order import repository as order_repo
from support import FakeAddSession
from transform.gold_quality import build_quality_rows, load_quality_mart
from transform.gold_readings import existing_reading_ids, load_gold_readings
from transform.gold_sentiment import load_sentiment_mart
from validation.quality_report import (
    build_reports,
    report_for_dataset,
    report_key,
    report_payload,
    run_great_expectations,
    write_reports,
)
from validation.validator import CleanBatch, QualityMetrics

pytestmark = pytest.mark.unit

DT = date(2026, 9, 1)


def _subscription(status: str) -> order_repo.Subscription:
    return order_repo.Subscription(
        subscription_id="sub_1",
        user_id="us_1",
        dataset_id="ds_weather-stations",
        interval_sec=300,
        status=status,
        started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_subscription_transitions_and_guards() -> None:
    assert next_status("SUB_ACTIVE", SubscriptionAction.PAUSE).value == "SUB_PAUSED"
    assert next_status("SUB_PAUSED", SubscriptionAction.RESUME).value == "SUB_ACTIVE"
    assert next_status("SUB_ACTIVE", SubscriptionAction.CANCEL).value == "SUB_CANCELLED"
    assert is_terminal("SUB_CANCELLED") is True
    assert is_streaming("SUB_ACTIVE") is True
    assert is_streaming("SUB_PAUSED") is False

    with pytest.raises(SubscriptionStateError):
        next_status("SUB_CANCELLED", SubscriptionAction.RESUME)


async def test_apply_transition_sets_cancelled_at() -> None:
    session = FakeAddSession()
    subscription = _subscription("SUB_ACTIVE")

    cancelled = await apply_transition(
        session,  # type: ignore[arg-type]
        subscription,
        SubscriptionAction.CANCEL,
        now=datetime(2026, 9, 18, tzinfo=UTC),
    )

    assert cancelled.status == "SUB_CANCELLED"
    assert cancelled.cancelled_at == datetime(2026, 9, 18, tzinfo=UTC)
    assert session.added == [subscription]


def test_quality_report_helpers() -> None:
    metrics = QualityMetrics(total=10, missing=1, duplicates=1, outliers=1, gaps=0)
    report = report_for_dataset(metrics, "ds_x", DT)

    assert report["dataset_id"] == "ds_x"
    assert report["anomalies_cnt"] == 1
    assert report_key(DT) == "reports/quality/2026-09-01/report.json"
    payload = report_payload(DT, {"ds_x": report})
    assert payload["datasets"]["ds_x"]["records"] == 10


def test_build_reports_and_empty_expectations() -> None:
    empty = pd.DataFrame({"reading_id": [], "value": []})
    expectations = run_great_expectations(empty)
    assert expectations == {"available": True, "success": True, "expectations": []}

    batch = CleanBatch(
        frame=empty,
        metrics_by_dataset={"ds_x": QualityMetrics(total=0)},
    )
    reports = build_reports(batch, DT)

    assert reports["ds_x"]["great_expectations"]["success"] is True
    assert reports["ds_x"]["quality_score"] == 1.0


class _FakeStore:
    def __init__(self) -> None:
        self.written: list[tuple[str, str, bytes, str]] = []

    async def put_bytes(
        self, bucket: str, key: str, body: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.written.append((bucket, key, body, content_type))


async def test_write_reports_handles_empty_and_non_empty() -> None:
    store = _FakeStore()

    assert await write_reports(store, "lake", DT, {}) is None
    assert store.written == []

    key = await write_reports(store, "lake", DT, {"ds_x": {"quality_score": 0.5}})
    assert key == report_key(DT)
    assert store.written[0][1] == key


class _FakeClickHouse:
    def __init__(self, existing: list[tuple[str]] | None = None) -> None:
        self.commands: list[str] = []
        self.inserted: list[tuple[str, list[list[Any]]]] = []
        self._existing = existing or []

    async def command(self, query: str) -> None:
        self.commands.append(query)

    async def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str] | None = None,
    ) -> None:
        self.inserted.append((table, [list(row) for row in data]))

    async def execute(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        rows = self._existing

        class _Result:
            result_rows = rows

        return _Result()


async def test_gold_marts_are_idempotent() -> None:
    client = _FakeClickHouse()
    quality_rows = build_quality_rows({"ds_x": {"dt": "2026-09-01", "quality_score": 0.9}})
    assert await load_quality_mart(client, []) == 0
    assert await load_quality_mart(client, quality_rows) == 1
    assert any("ALTER TABLE mart_quality_daily" in query for query in client.commands)

    assert await load_sentiment_mart(client, []) == 0
    assert await load_sentiment_mart(client, [[DT, "ds_x", 2, 4.0, 2.0, 1, 1]]) == 1

    assert await existing_reading_ids(client, DT) == set()
    assert await load_gold_readings(client, [], DT) == 0

    dedup_client = _FakeClickHouse(existing=[("rd_old",)])
    fresh = await load_gold_readings(dedup_client, [["rd_new", 1], ["rd_old", 2]], DT)
    assert fresh == 1
    assert dedup_client.inserted[0][0] == "fact_readings"


async def test_catalog_lookup_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _missing(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("catalog.repository.get_dataset", _missing)

    for call in (
        catalog_service.get_dataset(None, "ds_missing"),  # type: ignore[arg-type]
        catalog_service.get_schema(None, "ds_missing"),  # type: ignore[arg-type]
        catalog_service.get_sample(None, "ds_missing", FileFormat.CSV),  # type: ignore[arg-type]
    ):
        with pytest.raises(ApiError) as error:
            await call
        assert error.value.status_code == 404
