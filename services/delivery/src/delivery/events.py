"""Публикация ``commerce.downloads`` (T140, FR-025).

Канонические сборка и публикация события скачивания живут в
:mod:`delivery.downloads`; здесь добавлен Kafka-издатель и сведены экспорты,
чтобы сервис доставки имел единый модуль бизнес-событий.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from db.kafka import create_producer, produce_json

from .downloads import (
    DownloadPublisher,
    DownloadRecord,
    NullDownloadPublisher,
    build_download_event,
    publish_download,
)

__all__ = [
    "DownloadPublisher",
    "DownloadRecord",
    "KafkaDownloadPublisher",
    "NullDownloadPublisher",
    "build_download_event",
    "publish_download",
]


class KafkaDownloadPublisher:
    """Публикация события скачивания в Redpanda (Kafka API)."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: Any | None = None

    async def start(self) -> None:
        """Запустить producer (идемпотентно)."""
        if self._producer is not None:
            return
        self._producer = create_producer(self._bootstrap)
        await self._producer.start()

    async def stop(self) -> None:
        """Остановить producer."""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Опубликовать JSON-событие с ключом партиции."""
        await self.start()
        assert self._producer is not None
        await produce_json(self._producer, topic, dict(payload), key=key)
