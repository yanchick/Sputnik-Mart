"""Публикация ``sensors.readings.v1`` и ``sensors.readings.dlq`` (T113).

Валидные чтения публикуются с ключом партиции ``stationId`` (упорядочение по
станции, FR-013); битые — с ключом ``readingId``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from contracts import ContentTopic, SensorReadingPayload
from db.kafka import create_producer, produce_json


class ReadingPublisher(Protocol):
    """Абстракция публикации чтения (Kafka или no-op)."""

    async def publish(self, reading: SensorReadingPayload, key: str) -> None:
        """Опубликовать чтение с ключом партиции."""
        ...


class DeadReadingPublisher(Protocol):
    """Абстракция публикации битой записи в DLQ."""

    async def publish(self, reading: Mapping[str, Any], key: str) -> None:
        """Опубликовать битую запись с причиной."""
        ...


class NullPublisher:
    """No-op публикация для профиля ``base`` без Redpanda."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, reading: Any, key: str) -> None:
        """Запомнить публикацию в памяти (для тестов и base-профиля)."""
        payload = reading.model_dump(mode="json") if hasattr(reading, "model_dump") else reading
        self.published.append((key, dict(payload)))


class KafkaPublisher:
    """Публикация JSON-сообщений в Redpanda (Kafka API)."""

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap = bootstrap_servers
        self._topic = topic
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

    async def publish(self, reading: Any, key: str) -> None:
        """Опубликовать чтение в топик с ключом партиции."""
        await self.start()
        assert self._producer is not None
        payload = reading.model_dump(mode="json") if hasattr(reading, "model_dump") else reading
        await produce_json(self._producer, self._topic, dict(payload), key=key)

    async def publish_reading(self, reading: SensorReadingPayload, key: str) -> None:
        """Совместимый алиас :meth:`publish`."""
        await self.publish(reading, key)


def readings_topic() -> str:
    """Имя топика валидных чтений."""
    return ContentTopic.READINGS.value


def dlq_topic() -> str:
    """Имя топика битых чтений."""
    return ContentTopic.DLQ.value


__all__ = [
    "DeadReadingPublisher",
    "KafkaPublisher",
    "NullPublisher",
    "ReadingPublisher",
    "dlq_topic",
    "readings_topic",
]
