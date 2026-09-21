"""Kafka → bronze: at-least-once, дедупликация и DLQ (T114).

Валидные чтения пишутся в сырой слой ``lake/bronze/{provider}/{dt}`` без
изменения содержимого; повторные ``readingId`` и «ядовитые» сообщения уходят
в DLQ с причиной (FR-014, FR-015, FR-016).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from contracts import (
    DeadReadingPayload,
    DeadReadingReason,
    Metric,
    SensorReadingPayload,
    metric_bounds,
)
from observability import get_logger

from .dlq import DlqPublisher, build_dead_reading

_log = get_logger(__name__)

BRONZE_PREFIX = "bronze"


class Deduplicator(Protocol):
    """Дедупликация по ``readingId`` (Redis или память)."""

    async def mark(self, reading_id: str) -> bool:
        """Вернуть ``True``, если чтение встретилось впервые."""
        ...


class InMemoryDeduplicator:
    """Дедупликатор в памяти (тесты, один процесс)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def mark(self, reading_id: str) -> bool:
        """Запомнить ``readingId``; ``False`` — уже видели."""
        if reading_id in self._seen:
            return False
        self._seen.add(reading_id)
        return True


class RedisDeduplicator:
    """Строгий дедупликатор на Redis с TTL (at-least-once, FR-015)."""

    def __init__(self, store: Any, *, ttl_seconds: int = 86_400) -> None:
        self._store = store
        self._ttl = ttl_seconds

    async def mark(self, reading_id: str) -> bool:
        """Зарезервировать ``readingId`` атомарно."""
        return bool(await self._store.reserve(f"reading:{reading_id}", self._ttl))


class BronzeSink(Protocol):
    """Запись пачки сырых чтений в слой bronze."""

    async def write(self, provider_id: str, dt: date, records: Sequence[Mapping[str, Any]]) -> str:
        """Записать пачку и вернуть ключ объекта."""
        ...


class InMemoryBronzeSink:
    """Bronze в памяти: ключи и тела хранятся для проверок."""

    def __init__(self) -> None:
        self.objects: dict[str, list[dict[str, Any]]] = {}

    async def write(self, provider_id: str, dt: date, records: Sequence[Mapping[str, Any]]) -> str:
        """Сложить записи в память по ключу ``bronze/{provider}/{dt}``."""
        key = f"{BRONZE_PREFIX}/{provider_id}/{dt.isoformat()}/part-{len(self.objects):05d}"
        self.objects[key] = [dict(record) for record in records]
        return key


class MinioBronzeSink:
    """Bronze в MinIO: NDJSON без изменения содержимого."""

    def __init__(self, store: Any, bucket: str, *, prefix: str = BRONZE_PREFIX) -> None:
        self._store = store
        self._bucket = bucket
        self._prefix = prefix
        self._sequence = 0

    async def write(self, provider_id: str, dt: date, records: Sequence[Mapping[str, Any]]) -> str:
        """Записать NDJSON-объект и вернуть его ключ."""
        self._sequence += 1
        key = f"{self._prefix}/{provider_id}/{dt.isoformat()}/part-{self._sequence:05d}.ndjson"
        body = "\n".join(
            json.dumps(dict(record), ensure_ascii=False, default=str) for record in records
        )
        await self._store.put_bytes(self._bucket, key, body.encode("utf-8"), "application/x-ndjson")
        return key


@dataclass
class IngestionResult:
    """Итог обработки сообщения консьюмером."""

    written: int = 0
    duplicates: int = 0
    dead: list[DeadReadingPayload] = field(default_factory=list)


def _rejection_reason(message: Mapping[str, Any]) -> DeadReadingReason:
    """Определить причину отбраковки: пусто, вне границ или не та схема (FR-016)."""
    if "value" in message and message.get("value") is None:
        return DeadReadingReason.NULL_VALUE
    try:
        metric = Metric(str(message.get("metric")))
        value = float(message["value"])
    except (KeyError, TypeError, ValueError):
        return DeadReadingReason.SCHEMA_MISMATCH
    low, high = metric_bounds(metric)
    return (
        DeadReadingReason.SCHEMA_MISMATCH
        if low <= value <= high
        else DeadReadingReason.OUT_OF_RANGE
    )


def _parse_reading(message: Any) -> tuple[SensorReadingPayload | None, DeadReadingPayload | None]:
    """Разобрать сообщение Kafka в чтение или вернуть битую запись с причиной."""
    if not isinstance(message, Mapping):
        return None, build_dead_reading("", DeadReadingReason.SCHEMA_MISMATCH, {"value": message})
    try:
        reading = SensorReadingPayload.model_validate(dict(message))
    except Exception:  # граница разбора внешнего сообщения
        raw_id = str(message.get("readingId", ""))
        return None, build_dead_reading(raw_id, _rejection_reason(message), message)

    low, high = metric_bounds(reading.metric)
    if not low <= reading.value <= high:
        return None, build_dead_reading(reading.readingId, DeadReadingReason.OUT_OF_RANGE, message)
    return reading, None


class IngestionService:
    """Обработка потока чтений: дедупликация, bronze, DLQ."""

    def __init__(
        self,
        sink: BronzeSink,
        dlq: DlqPublisher,
        dedup: Deduplicator,
    ) -> None:
        self._sink = sink
        self._dlq = dlq
        self._dedup = dedup

    async def process_message(self, message: Any) -> IngestionResult:
        """Обработать одно сообщение: bronze для новых, DLQ для дублей/битых."""
        result = IngestionResult()
        reading, rejected = _parse_reading(message)
        if rejected is not None:
            await self._dlq.publish(rejected)
            result.dead.append(rejected)
            return result

        assert reading is not None
        if not await self._dedup.mark(reading.readingId):
            duplicate = build_dead_reading(reading.readingId, DeadReadingReason.DUPLICATE, message)
            await self._dlq.publish(duplicate)
            result.dead.append(duplicate)
            result.duplicates += 1
            return result

        measured_at = reading.measuredAt
        dt = measured_at.date() if isinstance(measured_at, datetime) else date.today()
        await self._sink.write(reading.providerId, dt, [reading.model_dump(mode="json")])
        result.written += 1
        return result

    async def process_batch(self, messages: Sequence[Any]) -> IngestionResult:
        """Обработать пачку сообщений (пустая пачка — пустой результат)."""
        combined = IngestionResult()
        for message in messages:
            single = await self.process_message(message)
            combined.written += single.written
            combined.duplicates += single.duplicates
            combined.dead.extend(single.dead)
        return combined


async def consume_readings(
    consumer: Any,
    service: IngestionService,
    *,
    max_messages: int | None = None,
) -> IngestionResult:
    """Читать Kafka-поток, коммитить оффсеты после обработки (at-least-once)."""
    total = IngestionResult()
    consumed = 0
    async for message in consumer:
        single = await service.process_message(message.value)
        total.written += single.written
        total.duplicates += single.duplicates
        total.dead.extend(single.dead)
        await consumer.commit()
        consumed += 1
        if max_messages is not None and consumed >= max_messages:
            break
    _log.info(
        "ingestion_batch_done",
        written=total.written,
        duplicates=total.duplicates,
        dead=len(total.dead),
    )
    return total


__all__ = [
    "BRONZE_PREFIX",
    "BronzeSink",
    "Deduplicator",
    "InMemoryBronzeSink",
    "InMemoryDeduplicator",
    "IngestionResult",
    "IngestionService",
    "MinioBronzeSink",
    "RedisDeduplicator",
    "consume_readings",
]
