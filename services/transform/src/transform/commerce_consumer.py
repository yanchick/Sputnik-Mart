"""Kafka-consumer ``commerce.*`` → gold-витрины (T147, FR-019, FR-025).

Рантайм-путь, которого не хватало: консьюмер читает пять топиков
``commerce.*``, дедуплицирует события по ``eventId`` (ключ
``commerce:event:{eventId}``, как ``readingId`` в ingestion) и накапливает
полную дневную агрегацию в памяти. При flush существующие transform-функции
строят строки витрин, а загрузка идемпотентно переписывает их по ключу
``(dt, dataset_id)``. Поэтому повторная доставка (at-least-once) не увеличивает
счётчики: дубли отсекаются, а перезапись полной агрегации не создаёт дублей.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from config import get_settings
from db import close_redis, create_consumer, create_redis
from db.clickhouse import create_client
from db.redis import IdempotencyStore
from observability import configure_logging, get_logger

from .commerce import COMMERCE_TOPICS, CommerceBatch, parse_commerce_event
from .gold_sales import load_sales_mart
from .gold_sentiment import load_sentiment_mart

_log = get_logger(__name__)

DEFAULT_DEDUP_TTL_SECONDS = 86_400
DEFAULT_FLUSH_EVERY = 100
EVENT_DEDUP_PREFIX = "commerce:event:"
CONSUMER_GROUP = "transform-commerce"

STATUS_ACCEPTED = "accepted"
STATUS_DUPLICATE = "duplicate"
STATUS_INVALID = "invalid"


class EventDeduplicator(Protocol):
    """Дедупликация commerce-событий по ``eventId``."""

    async def mark(self, event_id: str) -> bool:
        """Вернуть ``True``, если событие встретилось впервые."""
        ...


class InMemoryEventDeduplicator:
    """Дедупликатор в памяти (тесты, один процесс)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def mark(self, event_id: str) -> bool:
        """Запомнить ``eventId``; ``False`` — уже видели."""
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True


class RedisEventDeduplicator:
    """Строгий дедупликатор на Redis с TTL (at-least-once)."""

    def __init__(
        self, store: IdempotencyStore, *, ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds

    async def mark(self, event_id: str) -> bool:
        """Зарезервировать ``eventId`` атомарно (``SET NX``)."""
        return await self._store.reserve(f"{EVENT_DEDUP_PREFIX}{event_id}", self._ttl)


@dataclass
class CommerceResult:
    """Итог обработки commerce-потока."""

    accepted: int = 0
    duplicates: int = 0
    invalid: int = 0
    loaded_sales: int = 0
    loaded_sentiment: int = 0

    @property
    def loaded(self) -> int:
        """Всего загруженных строк витрин."""
        return self.loaded_sales + self.loaded_sentiment


class CommerceTransformService:
    """Накапливать события и идемпотентно загружать бизнес-витрины."""

    def __init__(self, client: Any, dedup: EventDeduplicator) -> None:
        self._client = client
        self._dedup = dedup
        self._batch = CommerceBatch()

    async def process_message(self, topic: str, message: Any) -> str:
        """Разобрать, дедуплицировать и накопить одно событие."""
        event = parse_commerce_event(topic, message)
        if event is None:
            return STATUS_INVALID
        if not await self._dedup.mark(event.event_id):
            return STATUS_DUPLICATE
        if not self._batch.add(event):
            return STATUS_INVALID
        return STATUS_ACCEPTED

    async def process_batch(self, topic: str, messages: Sequence[Any]) -> CommerceResult:
        """Обработать пачку сообщений одного топика (пустая — пустой результат)."""
        result = CommerceResult()
        for message in messages:
            _accumulate(result, await self.process_message(topic, message))
        return result

    async def flush(self) -> dict[str, int]:
        """Загрузить накопленную агрегацию в ClickHouse; вернуть строки по витринам."""
        if self._batch.empty:
            return {"mart_sales_daily": 0, "mart_sentiment_daily": 0}
        sales = await load_sales_mart(self._client, self._batch.sales_rows())
        sentiment = await load_sentiment_mart(self._client, self._batch.sentiment_rows())
        return {"mart_sales_daily": sales, "mart_sentiment_daily": sentiment}


def _accumulate(result: CommerceResult, status: str) -> None:
    if status == STATUS_ACCEPTED:
        result.accepted += 1
    elif status == STATUS_DUPLICATE:
        result.duplicates += 1
    else:
        result.invalid += 1


async def consume_commerce(
    consumer: Any,
    service: CommerceTransformService,
    *,
    max_messages: int | None = None,
    flush_every: int = DEFAULT_FLUSH_EVERY,
) -> CommerceResult:
    """Читать commerce-поток, коммитить оффсеты и периодически грузить витрины.

    Длительный консьюмер не может ждать остановки, поэтому витрины
    переписываются каждые ``flush_every`` сообщений и один раз в конце.
    """
    total = CommerceResult()
    consumed = 0
    since_flush = 0
    async for message in consumer:
        _accumulate(total, await service.process_message(message.topic, message.value))
        await consumer.commit()
        consumed += 1
        since_flush += 1
        if flush_every > 0 and since_flush >= flush_every:
            _record_flush(total, await service.flush())
            since_flush = 0
        if max_messages is not None and consumed >= max_messages:
            break
    _record_flush(total, await service.flush())
    _log.info(
        "commerce_transform_done",
        accepted=total.accepted,
        duplicates=total.duplicates,
        invalid=total.invalid,
        loaded=total.loaded,
    )
    return total


def _record_flush(total: CommerceResult, flushed: dict[str, int]) -> None:
    total.loaded_sales = flushed["mart_sales_daily"]
    total.loaded_sentiment = flushed["mart_sentiment_daily"]


async def run_commerce_consumer(*, max_messages: int | None = None) -> CommerceResult:
    """Собрать зависимости и прогнать commerce-консьюмер (или до ``max_messages``)."""
    settings = get_settings()
    redis = create_redis(settings.redis.url)
    dedup = RedisEventDeduplicator(IdempotencyStore(redis))
    client = create_client(
        host=settings.clickhouse.host,
        port=settings.clickhouse.port,
        username=settings.clickhouse.user,
        password=settings.clickhouse.password,
        database=settings.clickhouse.database,
    )
    consumer = create_consumer(
        COMMERCE_TOPICS,
        CONSUMER_GROUP,
        settings.kafka.bootstrap_servers,
    )
    await consumer.start()
    try:
        return await consume_commerce(
            consumer, CommerceTransformService(client, dedup), max_messages=max_messages
        )
    finally:
        await consumer.stop()
        await close_redis(redis)
        await client.close()


def main() -> None:
    """Запустить commerce-консьюмер transform-service (профиль adv)."""
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="transform-commerce")
    asyncio.run(run_commerce_consumer())


__all__ = [
    "CONSUMER_GROUP",
    "DEFAULT_DEDUP_TTL_SECONDS",
    "DEFAULT_FLUSH_EVERY",
    "EVENT_DEDUP_PREFIX",
    "CommerceResult",
    "CommerceTransformService",
    "EventDeduplicator",
    "InMemoryEventDeduplicator",
    "RedisEventDeduplicator",
    "consume_commerce",
    "main",
    "run_commerce_consumer",
]
