"""Unit-тест SSE: кадры ``reading``/``ping`` и дедупликация (T136, FR-022)."""

from __future__ import annotations

import pytest
from delivery.idempotency import InMemoryReadingDeduplicator
from delivery.sse import ping_frame, reading_frame, stream_frames
from delivery.streams import StaticReadingSource

pytestmark = pytest.mark.unit

READINGS = [
    {"readingId": "rd_1", "datasetId": "ds_x", "metric": "TEMPERATURE", "value": 10.0},
    {"readingId": "rd_2", "datasetId": "ds_x", "metric": "TEMPERATURE", "value": 11.0},
]


def _reading_ids(frames: list[str]) -> list[str]:
    return [line[4:] for frame in frames for line in frame.splitlines() if line.startswith("id:")]


async def _collect(source: StaticReadingSource, dedup: InMemoryReadingDeduplicator) -> list[str]:
    return [
        frame
        async for frame in stream_frames(
            source.stream({"dataset_id": "ds_x"}), dedup, ping_interval=1
        )
    ]


def test_reading_frame_has_id_and_event() -> None:
    frame = reading_frame(READINGS[0])

    assert frame.startswith("event: reading\nid: rd_1\n")
    assert '"readingId": "rd_1"' in frame
    assert frame.endswith("\n\n")


def test_ping_frame_is_keep_alive() -> None:
    frame = ping_frame()

    assert frame == "event: ping\ndata: {}\n\n"


async def test_stream_emits_unique_reading_ids_on_reconnect() -> None:
    source = StaticReadingSource(READINGS)
    dedup = InMemoryReadingDeduplicator()

    first = await _collect(source, dedup)
    assert any(frame.startswith("event: ping") for frame in first)
    assert _reading_ids(first) == ["rd_1", "rd_2"]

    # Переподключение: те же чтения уже зарезервированы — кадров reading нет.
    second = await _collect(source, dedup)
    assert _reading_ids(second) == []


async def test_empty_source_still_emits_ping() -> None:
    frames = await _collect(StaticReadingSource([]), InMemoryReadingDeduplicator())

    assert frames == ["event: ping\ndata: {}\n\n"]


def test_reading_without_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        reading_frame({"value": 1})
