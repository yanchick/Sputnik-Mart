"""Unit-тесты sensor-gateway: ``receivedAt`` ставит только шлюз (T102)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from contracts import ContentTopic, DeadReadingReason
from sensor_gateway.main import create_app
from sensor_gateway.publisher import NullPublisher, dlq_topic, readings_topic
from sensor_gateway.service import ReadingProcessor, classify_reading

pytestmark = pytest.mark.unit

CLOCK = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _valid(**overrides: object) -> dict[str, object]:
    reading: dict[str, object] = {
        "readingId": "rd_1",
        "stationId": "st_1",
        "providerId": "pv_meteo",
        "metric": "TEMPERATURE",
        "value": 18.4,
        "unit": "C",
        "geo": {"lat": 59.9, "lon": 30.3},
        "measuredAt": "2026-09-01T11:00:00+00:00",
    }
    reading.update(overrides)
    return reading


def test_received_at_is_set_only_by_gateway() -> None:
    accepted, rejected = classify_reading(
        _valid(receivedAt="2000-01-01T00:00:00+00:00"), received_at=CLOCK
    )
    assert rejected is None
    assert accepted is not None
    assert accepted.receivedAt == CLOCK
    assert accepted.measuredAt == datetime(2026, 9, 1, 11, 0, tzinfo=UTC)


def test_null_value_goes_to_dlq_with_null_reason() -> None:
    accepted, rejected = classify_reading(_valid(value=None), received_at=CLOCK)
    assert accepted is None
    assert rejected is not None
    assert rejected.reason is DeadReadingReason.NULL_VALUE


def test_out_of_range_value_goes_to_dlq() -> None:
    accepted, rejected = classify_reading(_valid(value=500.0), received_at=CLOCK)
    assert accepted is None
    assert rejected is not None
    assert rejected.reason is DeadReadingReason.OUT_OF_RANGE


def test_schema_mismatch_goes_to_dlq() -> None:
    accepted, rejected = classify_reading({"readingId": "rd_x"}, received_at=CLOCK)
    assert accepted is None
    assert rejected is not None
    assert rejected.reason is DeadReadingReason.SCHEMA_MISMATCH


def test_processor_empty_input_is_safe() -> None:
    result = ReadingProcessor(clock=lambda: CLOCK).ingest([])
    assert result.accepted == ()
    assert result.dead == ()


async def test_malformed_json_returns_bad_request() -> None:
    """QR-5: битый JSON — 400 в едином конверте, а не 500."""
    app = create_app(
        processor=ReadingProcessor(clock=lambda: CLOCK),
        readings=NullPublisher(),
        dead_letters=NullPublisher(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/readings",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    payload = response.json()["error"]
    assert payload["code"] == "BAD_REQUEST"
    assert "requestId" in payload


async def test_post_readings_publishes_valid_and_dlq() -> None:
    readings = NullPublisher()
    dead_letters = NullPublisher()
    app = create_app(
        processor=ReadingProcessor(clock=lambda: CLOCK),
        readings=readings,
        dead_letters=dead_letters,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/readings", json=[_valid(), _valid(value=None, readingId="rd_2")]
        )
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "dead": 1}
    assert len(readings.published) == 1
    assert readings.published[0][0] == "st_1"
    assert len(dead_letters.published) == 1


def test_sensor_gateway_is_a_dlq_producer() -> None:
    """m7: шлюз легитимно публикует битые чтения в ``sensors.readings.dlq``."""
    assert readings_topic() == ContentTopic.READINGS.value == "sensors.readings.v1"
    assert dlq_topic() == ContentTopic.DLQ.value == "sensors.readings.dlq"


async def test_publisher_emits_clean_two_tuple_payload() -> None:
    """QR-7: в памяти публикации лежит ``(key, payload)`` без дубля ключа."""
    dead_letters = NullPublisher()
    app = create_app(
        processor=ReadingProcessor(clock=lambda: CLOCK),
        readings=NullPublisher(),
        dead_letters=dead_letters,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/api/v1/readings", json=[_valid(value=None, readingId="rd_2")])

    key, payload = dead_letters.published[0]
    assert key == "rd_2"
    assert payload["readingId"] == "rd_2"
    assert len(dead_letters.published[0]) == 2
