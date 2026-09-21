"""Публикация commerce-событий заказов и подписок (T080)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from contracts import CommerceTopic, OrderEventPayload, SubscriptionEventPayload
from db.kafka import create_producer, produce_json

from .repository import Order, Subscription


class EventPublisher(Protocol):
    """Абстракция публикации событий (Kafka или no-op в профиле base)."""

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Опубликовать событие в топик с ключом партиции."""
        ...


class NullPublisher:
    """Заглушка публикации для профиля ``base`` без Redpanda."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], str]] = []

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        self.published.append((topic, dict(payload), key))


class KafkaEventPublisher:
    """Публикация событий в Redpanda (Kafka API)."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: Any | None = None

    async def start(self) -> None:
        """Запустить producer."""
        self._producer = create_producer(self._bootstrap)
        await self._producer.start()

    async def stop(self) -> None:
        """Остановить producer."""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Опубликовать JSON-событие."""
        if self._producer is None:
            await self.start()
        assert self._producer is not None
        await produce_json(self._producer, topic, dict(payload), key=key)


def build_order_event(order: Order, user_id: str) -> dict[str, Any]:
    """Собрать payload ``commerce.orders`` для заказа."""
    event = OrderEventPayload(
        eventId=f"ev_{order.order_id}",
        userId=user_id,
        at=order.created_at or datetime.now(UTC),
        orderId=order.order_id,
        datasetId=order.dataset_id,
        amount=float(order.amount),
    )
    return event.model_dump(mode="json")


def build_subscription_event(subscription: Subscription, user_id: str) -> dict[str, Any]:
    """Собрать payload ``commerce.subscriptions`` для подписки."""
    event = SubscriptionEventPayload(
        eventId=f"ev_{subscription.subscription_id}",
        userId=user_id,
        at=subscription.started_at or datetime.now(UTC),
        subscriptionId=subscription.subscription_id,
        datasetId=subscription.dataset_id,
        intervalSec=subscription.interval_sec,
    )
    return event.model_dump(mode="json")


async def publish_order(publisher: EventPublisher, order: Order, user_id: str) -> None:
    """Опубликовать событие создания заказа."""
    await publisher.publish(
        CommerceTopic.ORDERS.value, build_order_event(order, user_id), order.order_id
    )


async def publish_subscription(
    publisher: EventPublisher, subscription: Subscription, user_id: str
) -> None:
    """Опубликовать событие оформления подписки."""
    await publisher.publish(
        CommerceTopic.SUBSCRIPTIONS.value,
        build_subscription_event(subscription, user_id),
        subscription.subscription_id,
    )


__all__ = [
    "EventPublisher",
    "KafkaEventPublisher",
    "NullPublisher",
    "build_order_event",
    "build_subscription_event",
    "publish_order",
    "publish_subscription",
]
