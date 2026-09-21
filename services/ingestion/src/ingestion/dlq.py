"""Очередь ошибок ingestion: публикация и архив ``lake/dlq`` (T115).

Битые записи публикуются в ``sensors.readings.dlq`` с причиной и архивируются
в ``lake/dlq/{topic}/{dt}/part-*.ndjson`` (FR-016).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Protocol

from contracts import ContentTopic, DeadReadingPayload, DeadReadingReason


def build_dead_reading(
    reading_id: str,
    reason: DeadReadingReason,
    raw: Mapping[str, Any],
) -> DeadReadingPayload:
    """Собрать битую запись с причиной отклонения."""
    return DeadReadingPayload(readingId=reading_id or "rd_unknown", reason=reason, raw=dict(raw))


class DlqPublisher(Protocol):
    """Публикация битой записи в Kafka DLQ."""

    async def publish(self, dead: DeadReadingPayload) -> None:
        """Опубликовать битую запись."""
        ...


class InMemoryDlq:
    """DLQ в памяти для unit-тестов и профиля ``base``."""

    def __init__(self) -> None:
        self.dead: list[DeadReadingPayload] = []

    async def publish(self, dead: DeadReadingPayload) -> None:
        """Запомнить битую запись."""
        self.dead.append(dead)


class MinioDlqArchive:
    """Архив DLQ в MinIO ``lake/dlq/{topic}/{dt}/part-*.ndjson``."""

    def __init__(self, store: Any, bucket: str, *, prefix: str = "dlq") -> None:
        self._store = store
        self._bucket = bucket
        self._prefix = prefix
        self._sequence = 0

    def _next_key(self, topic: str, dt: date) -> str:
        self._sequence += 1
        return f"{self._prefix}/{topic}/{dt.isoformat()}/part-{self._sequence:05d}.ndjson"

    async def archive(
        self, topic: str, dt: date, records: Sequence[Mapping[str, Any]]
    ) -> str | None:
        """Записать пачку битых записей; ``None`` — если записей нет."""
        if not records:
            return None
        key = self._next_key(topic, dt)
        body = "\n".join(json.dumps(dict(record), ensure_ascii=False) for record in records)
        await self._store.put_bytes(self._bucket, key, body.encode("utf-8"), "application/x-ndjson")
        return key


class KafkaDlqPublisher:
    """Публикация битых записей в ``sensors.readings.dlq``."""

    def __init__(self, bootstrap_servers: str, topic: str = ContentTopic.DLQ.value) -> None:
        self._bootstrap = bootstrap_servers
        self._topic = topic
        self._producer: Any | None = None

    async def start(self) -> None:
        """Запустить producer (идемпотентно)."""
        from db.kafka import create_producer

        if self._producer is None:
            self._producer = create_producer(self._bootstrap)
            await self._producer.start()

    async def stop(self) -> None:
        """Остановить producer."""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, dead: DeadReadingPayload) -> None:
        """Опубликовать JSON-запись с ключом ``readingId``."""
        from db.kafka import produce_json

        await self.start()
        assert self._producer is not None
        await produce_json(
            self._producer, self._topic, dead.model_dump(mode="json"), key=dead.readingId
        )


__all__ = [
    "DlqPublisher",
    "InMemoryDlq",
    "KafkaDlqPublisher",
    "MinioDlqArchive",
    "build_dead_reading",
]
