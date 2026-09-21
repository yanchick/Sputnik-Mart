"""Кадры Server-Sent Events живого потока (T143, ADR-0003).

Кадр чтения несёт ``event: reading`` и ``id = readingId`` — именно ``id``
позволяет клиенту (httpx-sse, браузер) переподключаться без дублей.
Keep-alive реализован кадром ``event: ping``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from typing import Any

from contracts import SseEventName

from .idempotency import ReadingDeduplicator

SSE_MEDIA_TYPE = "text/event-stream"
DEFAULT_PING_INTERVAL_SECONDS = 15.0


def reading_id_of(reading: Mapping[str, Any]) -> str:
    """Извлечь идентификатор чтения (ключ дедупликации и ``id`` кадра)."""
    value = reading.get("readingId") or reading.get("reading_id")
    if not value:
        raise ValueError("Чтение без readingId не может быть отправлено в поток")
    return str(value)


def format_frame(event: SseEventName, data: Mapping[str, Any], event_id: str | None = None) -> str:
    """Собрать SSE-кадр: ``event``, опциональный ``id`` и JSON-``data``."""
    lines = [f"event: {event.value}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(dict(data), ensure_ascii=False, default=str)}")
    return "\n".join(lines) + "\n\n"


def reading_frame(reading: Mapping[str, Any]) -> str:
    """Кадр ``event: reading`` с ``id = readingId``."""
    return format_frame(SseEventName.READING, reading, reading_id_of(reading))


def ping_frame() -> str:
    """Кадр keep-alive ``event: ping``."""
    return format_frame(SseEventName.PING, {})


async def stream_frames(
    readings: AsyncIterator[Mapping[str, Any]],
    deduplicator: ReadingDeduplicator,
    *,
    ping_interval: float = DEFAULT_PING_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Отдавать кадры чтений без дублей, вставляя ``ping`` по таймауту.

    Источник может быть бесконечным (production ClickHouse), поэтому выборка
    вынесена в фоновую задачу, а ожидание ограничено ``ping_interval``.
    """
    yield ping_frame()
    queue: asyncio.Queue[tuple[str, Mapping[str, Any] | None]] = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for reading in readings:
                await queue.put(("reading", reading))
        finally:
            await queue.put(("end", None))

    pump = asyncio.create_task(_pump())
    try:
        while True:
            try:
                timeout = ping_interval if ping_interval > 0 else None
                kind, reading = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                yield ping_frame()
                continue
            if kind == "end":
                return
            assert reading is not None
            if await deduplicator.reserve(reading_id_of(reading)):
                yield reading_frame(reading)
    finally:
        pump.cancel()
        with suppress(asyncio.CancelledError):
            await pump


__all__ = [
    "DEFAULT_PING_INTERVAL_SECONDS",
    "SSE_MEDIA_TYPE",
    "format_frame",
    "ping_frame",
    "reading_frame",
    "reading_id_of",
    "stream_frames",
]
