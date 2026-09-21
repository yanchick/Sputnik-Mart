"""Kafka producer/consumer на aiokafka (Redpanda, Kafka API)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


def _encode_json(value: Any) -> bytes:
    return json.dumps(value, default=str).encode("utf-8")


def _decode_json(raw: bytes | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def create_producer(bootstrap_servers: str) -> AIOKafkaProducer:
    """Создать JSON-producer без автозапуска."""
    return AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=_encode_json,
        enable_idempotence=True,
    )


def create_consumer(
    topics: Iterable[str],
    group_id: str,
    bootstrap_servers: str,
    *,
    auto_offset_reset: str = "earliest",
    enable_auto_commit: bool = False,
) -> AIOKafkaConsumer:
    """Создать JSON-consumer без автозапуска (at-least-once)."""
    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        enable_auto_commit=enable_auto_commit,
        value_deserializer=_decode_json,
    )


async def produce_json(
    producer: AIOKafkaProducer, topic: str, value: Any, key: str | None = None
) -> None:
    """Отправить JSON-сообщение с опциональным ключом партиции."""
    encoded_key = key.encode("utf-8") if key is not None else None
    await producer.send_and_wait(topic, value=value, key=encoded_key)


async def stream_json(
    consumer: AIOKafkaConsumer, *, max_messages: int | None = None
) -> AsyncIterator[Any]:
    """Асинхронно отдавать декодированные сообщения консьюмера."""
    consumed = 0
    async for message in consumer:
        yield message.value
        consumed += 1
        if max_messages is not None and consumed >= max_messages:
            return


__all__ = [
    "create_consumer",
    "create_producer",
    "produce_json",
    "stream_json",
]
