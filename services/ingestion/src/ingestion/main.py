"""Точка входа ingestion: Kafka → bronze с дедупликацией и DLQ (T114/T115)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from config import get_settings
from contracts import ContentTopic, DeadReadingPayload
from db import (
    IdempotencyStore,
    close_redis,
    create_consumer,
    create_object_store,
    create_redis,
)
from observability import configure_logging, get_logger

from .consumer import (
    IngestionResult,
    IngestionService,
    MinioBronzeSink,
    RedisDeduplicator,
    consume_readings,
)
from .dlq import KafkaDlqPublisher, MinioDlqArchive

_log = get_logger(__name__)


class CompositeDlq:
    """Публикация битой записи в Kafka и архив MinIO одновременно."""

    def __init__(self, publisher: KafkaDlqPublisher, archive: MinioDlqArchive) -> None:
        self._publisher = publisher
        self._archive = archive

    async def publish(self, dead: DeadReadingPayload) -> None:
        """Опубликовать в Kafka и сохранить в архив."""
        await self._publisher.publish(dead)
        await self._archive.archive(
            ContentTopic.DLQ.value,
            datetime.now(UTC).date(),
            [dead.model_dump(mode="json")],
        )


async def run_ingestion(*, max_messages: int | None = None) -> IngestionResult:
    """Собрать зависимости и прогнать консьюмер (или до ``max_messages``)."""
    settings = get_settings()
    store = create_object_store(
        endpoint_url=settings.minio.endpoint,
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name=settings.minio.region,
    )
    await store.ensure_bucket(settings.minio.lake_bucket)
    redis = create_redis(settings.redis.url)
    dedup = RedisDeduplicator(IdempotencyStore(redis))
    sink = MinioBronzeSink(store, settings.minio.lake_bucket)
    publisher = KafkaDlqPublisher(settings.kafka.bootstrap_servers)
    archive = MinioDlqArchive(store, settings.minio.lake_bucket)
    service = IngestionService(sink, CompositeDlq(publisher, archive), dedup)

    consumer = create_consumer(
        [ContentTopic.READINGS.value],
        "ingestion-bronze",
        settings.kafka.bootstrap_servers,
    )
    await consumer.start()
    try:
        result = await consume_readings(consumer, service, max_messages=max_messages)
    finally:
        await consumer.stop()
        await publisher.stop()
        await close_redis(redis)
    _log.info(
        "ingestion_done",
        written=result.written,
        duplicates=result.duplicates,
        dead=len(result.dead),
    )
    return result


def main() -> None:
    """Запустить ingestion-консьюмер."""
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="ingestion")
    asyncio.run(run_ingestion())


__all__ = ["CompositeDlq", "main", "run_ingestion"]
