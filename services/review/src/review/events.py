"""Публикация ``commerce.reviews`` (T083)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from contracts import CommerceTopic, ReviewEventPayload
from db.kafka import create_producer, produce_json
from observability.masking import mask_text

from .repository import Review


class ReviewPublisher(Protocol):
    """Абстракция публикации отзывов."""

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Опубликовать событие отзыва."""
        ...


class NullReviewPublisher:
    """No-op публикация без Redpanda (профиль ``base``)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], str]] = []

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        self.published.append((topic, dict(payload), key))


class KafkaReviewPublisher:
    """Публикация ``commerce.reviews`` в Redpanda (Kafka API)."""

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
        """Опубликовать событие отзыва с ключом партиции."""
        await self.start()
        assert self._producer is not None
        await produce_json(self._producer, topic, dict(payload), key=key)


def build_review_event(review: Review) -> dict[str, Any]:
    """Собрать payload ``commerce.reviews`` (текст замаскирован, m8)."""
    event = ReviewEventPayload(
        eventId=f"ev_{review.review_id}",
        userId=review.user_id,
        at=review.created_at or datetime.now(UTC),
        reviewId=review.review_id,
        datasetId=review.dataset_id,
        rating=review.rating,
        text=mask_text(review.text) if review.text else "",
    )
    return event.model_dump(mode="json")


async def publish_review(publisher: ReviewPublisher, review: Review) -> None:
    """Опубликовать событие отзыва."""
    await publisher.publish(
        CommerceTopic.REVIEWS.value, build_review_event(review), review.review_id
    )


__all__ = [
    "KafkaReviewPublisher",
    "NullReviewPublisher",
    "ReviewPublisher",
    "build_review_event",
    "publish_review",
]
