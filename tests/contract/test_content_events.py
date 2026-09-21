"""Контрактный тест событий ``sensors.readings.v1`` и DLQ (T101)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from contracts import (
    ContentTopic,
    DeadReadingPayload,
    DeadReadingReason,
    Metric,
    SensorReadingPayload,
)

pytestmark = pytest.mark.contract


def _content_schema(project_root: Path) -> dict[str, Any]:
    contract = project_root / "specs" / "001-sputnik-data-portal" / "contracts"
    document = yaml.safe_load((contract / "asyncapi-content.yaml").read_text(encoding="utf-8"))
    return dict(document["components"]["schemas"])


def test_sensor_reading_required_fields_match_contract(project_root: Path) -> None:
    schema = _content_schema(project_root)["SensorReadingPayload"]
    required = set(schema["required"])
    model_required = {
        name for name, field in SensorReadingPayload.model_fields.items() if field.is_required()
    }
    assert required <= set(SensorReadingPayload.model_fields)
    assert required == model_required


def test_dead_reading_reason_enum_matches_contract(project_root: Path) -> None:
    schema = _content_schema(project_root)["DeadReadingPayload"]
    declared = set(schema["properties"]["reason"]["enum"])
    assert declared == {reason.value for reason in DeadReadingReason}


def test_metric_enum_matches_contract(project_root: Path) -> None:
    schema = _content_schema(project_root)["Metric"]
    assert set(schema["enum"]) == {metric.value for metric in Metric}


def test_sensor_reading_round_trip_preserves_received_at() -> None:
    payload = SensorReadingPayload(
        readingId="rd_1",
        stationId="st_1",
        providerId="pv_1",
        metric=Metric.TEMPERATURE,
        value=18.4,
        unit="C",
        measuredAt=datetime(2026, 9, 1, tzinfo=UTC),
        receivedAt=datetime(2026, 9, 1, 0, 1, tzinfo=UTC),
    )
    restored = SensorReadingPayload.model_validate(payload.model_dump(mode="json"))
    assert restored.receivedAt == payload.receivedAt
    assert restored.measuredAt == payload.measuredAt


def test_dlq_topic_names_match_contract() -> None:
    assert ContentTopic.READINGS.value == "sensors.readings.v1"
    assert ContentTopic.DLQ.value == "sensors.readings.dlq"
    dead = DeadReadingPayload(
        readingId="rd_bad", reason=DeadReadingReason.NULL_VALUE, raw={"value": None}
    )
    assert dead.reason is DeadReadingReason.NULL_VALUE
