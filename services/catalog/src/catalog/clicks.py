"""Публикация ``commerce.clicks`` из каталога (T139, FR-025, ADR-0005).

Событие формируется плоским конвертом ``EventEnvelope`` + поля топика
(см. ``asyncapi-commerce.yaml``): ``{eventId, userId, at, datasetId, source}``.
Ключ партиции — ``datasetId``; ``eventId`` уникален и служит ключом
идемпотентности потребителя.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from contracts import ClickEventPayload, ClickSource, CommerceTopic
from db.kafka import create_producer, produce_json


class ClickPublisher(Protocol):
    """Абстракция публикации кликов (Kafka или no-op)."""

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Опубликовать событие с ключом партиции."""
        ...


class NullClickPublisher:
    """No-op публикация для профиля ``base`` без Redpanda."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], str]] = []

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Запомнить публикацию в памяти (для тестов и base-профиля)."""
        self.published.append((topic, dict(payload), key))


class KafkaClickPublisher:
    """Публикация ``commerce.clicks`` в Redpanda (Kafka API)."""

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
        """Опубликовать событие клика с ключом партиции."""
        await self.start()
        assert self._producer is not None
        await produce_json(self._producer, topic, dict(payload), key=key)


def build_click_event(
    dataset_id: str,
    user_id: str,
    source: ClickSource,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Собрать плоский payload ``commerce.clicks``."""
    event = ClickEventPayload(
        eventId=f"ev_{uuid.uuid4().hex[:12]}",
        userId=user_id,
        at=at or datetime.now(UTC),
        datasetId=dataset_id,
        source=source,
    )
    return event.model_dump(mode="json")


async def publish_click(
    publisher: ClickPublisher,
    dataset_id: str,
    user_id: str,
    source: ClickSource,
) -> None:
    """Опубликовать событие просмотра карточки/образца датасета."""
    await publisher.publish(
        CommerceTopic.CLICKS.value,
        build_click_event(dataset_id, user_id, source),
        dataset_id,
    )


__all__ = [
    "ClickPublisher",
    "KafkaClickPublisher",
    "NullClickPublisher",
    "build_click_event",
    "publish_click",
]
