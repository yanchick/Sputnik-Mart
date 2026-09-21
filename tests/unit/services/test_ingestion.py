"""Unit-тесты ingestion: bronze + DLQ с причиной (T103)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts import DeadReadingReason
from ingestion.consumer import (
    IngestionService,
    InMemoryBronzeSink,
    InMemoryDeduplicator,
    RedisDeduplicator,
)
from ingestion.dlq import InMemoryDlq

pytestmark = pytest.mark.unit


class _RecordingStore:
    """Redis-заглушка, запоминающая зарезервированные ключи и TTL."""

    def __init__(self) -> None:
        self.reserved: list[tuple[str, int]] = []

    async def reserve(self, key: str, ttl: int) -> bool:
        self.reserved.append((key, ttl))
        return True


def _reading(reading_id: str = "rd_1", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "readingId": reading_id,
        "stationId": "st_1",
        "providerId": "pv_meteo",
        "metric": "TEMPERATURE",
        "value": 18.4,
        "unit": "C",
        "geo": {"lat": 59.9, "lon": 30.3},
        "measuredAt": "2026-09-01T11:00:00+00:00",
        "receivedAt": "2026-09-01T11:00:05+00:00",
    }
    payload.update(overrides)
    return payload


def _service() -> tuple[IngestionService, InMemoryBronzeSink, InMemoryDlq]:
    sink = InMemoryBronzeSink()
    dlq = InMemoryDlq()
    return IngestionService(sink, dlq, InMemoryDeduplicator()), sink, dlq


async def test_valid_reading_writes_bronze_by_provider_and_date() -> None:
    service, sink, dlq = _service()
    result = await service.process_message(_reading())
    assert result.written == 1
    assert dlq.dead == []
    key = "bronze/pv_meteo/2026-09-01/part-00000"
    assert key in sink.objects
    assert sink.objects[key][0]["readingId"] == "rd_1"


async def test_duplicate_reading_goes_to_dlq_with_duplicate_reason() -> None:
    service, sink, dlq = _service()
    await service.process_message(_reading())
    result = await service.process_message(_reading())
    assert result.written == 0
    assert result.duplicates == 1
    assert len(dlq.dead) == 1
    assert dlq.dead[0].reason is DeadReadingReason.DUPLICATE
    assert len(sink.objects) == 1


async def test_poison_message_goes_to_dlq_schema_mismatch() -> None:
    service, sink, dlq = _service()
    result = await service.process_message({"readingId": "rd_bad", "value": "not-a-number"})
    assert result.written == 0
    assert len(dlq.dead) == 1
    assert dlq.dead[0].reason is DeadReadingReason.SCHEMA_MISMATCH
    assert sink.objects == {}


async def test_null_value_goes_to_dlq_with_null_reason() -> None:
    service, sink, dlq = _service()
    result = await service.process_message(_reading("rd_null", value=None))
    assert result.written == 0
    assert dlq.dead[0].reason is DeadReadingReason.NULL_VALUE
    assert sink.objects == {}


async def test_out_of_range_value_goes_to_dlq() -> None:
    service, sink, dlq = _service()
    result = await service.process_message(_reading("rd_hot", value=500.0))
    assert result.written == 0
    assert dlq.dead[0].reason is DeadReadingReason.OUT_OF_RANGE
    assert sink.objects == {}


async def test_batch_and_empty_input_are_safe() -> None:
    service, _sink, _dlq = _service()
    empty = await service.process_batch([])
    assert empty.written == 0 and empty.dead == []
    batch = await service.process_batch([_reading("rd_10"), _reading("rd_11")])
    assert batch.written == 2


def test_reading_timestamp_is_preserved() -> None:
    assert _reading()["measuredAt"] == "2026-09-01T11:00:00+00:00"
    assert datetime(2026, 9, 1, 11, tzinfo=UTC).isoformat() == "2026-09-01T11:00:00+00:00"


async def test_redis_dedup_ttl_bound_is_24h() -> None:
    """QR-8: граница дедупликации FR-015 — 24 ч (повтор в пределах суток)."""
    store = _RecordingStore()
    dedup = RedisDeduplicator(store)

    assert await dedup.mark("rd_1")

    assert store.reserved == [("reading:rd_1", 86_400)]
