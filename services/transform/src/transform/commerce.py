"""Commerce-события → строки бизнес-витрин (FR-019, FR-025).

Модуль отделяет разбор внешнего wire-формата от агрегации: событие топика
``commerce.*`` парсится в доверенный :class:`CommerceEvent`, накапливается в
:class:`CommerceBatch`, а затем существующие transform-функции строят строки
``mart_sales_daily``/``mart_sentiment_daily``. Невалидные сообщения отсекаются
на границе и не попадают во внутреннюю логику.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts import (
    ClickEventPayload,
    CommerceTopic,
    DownloadEventPayload,
    EventEnvelope,
    OrderEventPayload,
    ReviewEventPayload,
    SubscriptionEventPayload,
)

from .gold_sales import build_sales_rows
from .gold_sentiment import build_sentiment_rows

SALES_TOPICS: frozenset[str] = frozenset(
    {
        CommerceTopic.ORDERS.value,
        CommerceTopic.SUBSCRIPTIONS.value,
        CommerceTopic.DOWNLOADS.value,
        CommerceTopic.CLICKS.value,
    }
)
SENTIMENT_TOPICS: frozenset[str] = frozenset({CommerceTopic.REVIEWS.value})

# Топик → pydantic-модель payload и имя накопителя в CommerceBatch.
_PAYLOAD_MODELS: dict[str, tuple[type[EventEnvelope], str]] = {
    CommerceTopic.ORDERS.value: (OrderEventPayload, "orders"),
    CommerceTopic.SUBSCRIPTIONS.value: (SubscriptionEventPayload, "subscriptions"),
    CommerceTopic.DOWNLOADS.value: (DownloadEventPayload, "downloads"),
    CommerceTopic.CLICKS.value: (ClickEventPayload, "clicks"),
    CommerceTopic.REVIEWS.value: (ReviewEventPayload, "reviews"),
}

COMMERCE_TOPICS: tuple[str, ...] = tuple(topic.value for topic in CommerceTopic)


@dataclass(frozen=True)
class CommerceEvent:
    """Разобранное commerce-событие с ключом идемпотентности ``eventId``."""

    topic: str
    event_id: str
    payload: dict[str, Any]


def parse_commerce_event(topic: str, message: Any) -> CommerceEvent | None:
    """Разобрать сообщение в событие; ``None`` — неизвестный топик или битый payload."""
    model_and_bucket = _PAYLOAD_MODELS.get(topic)
    if model_and_bucket is None or not isinstance(message, Mapping):
        return None
    model, _bucket = model_and_bucket
    try:
        parsed = model.model_validate(dict(message))
    except Exception:  # граница разбора внешнего сообщения (FR-016-совместимо)
        return None
    return CommerceEvent(
        topic=topic,
        event_id=parsed.eventId,
        payload=parsed.model_dump(mode="json"),
    )


@dataclass
class CommerceBatch:
    """Накопитель разобранных событий по видам бизнес-активности."""

    orders: list[dict[str, Any]] = field(default_factory=list)
    subscriptions: list[dict[str, Any]] = field(default_factory=list)
    downloads: list[dict[str, Any]] = field(default_factory=list)
    clicks: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """Пустой ли накопитель (нечего загружать)."""
        return not (
            self.orders or self.subscriptions or self.downloads or self.clicks or self.reviews
        )

    def add(self, event: CommerceEvent) -> bool:
        """Добавить событие; ``False`` — у топика нет накопителя."""
        model_and_bucket = _PAYLOAD_MODELS.get(event.topic)
        if model_and_bucket is None:
            return False
        _model, bucket = model_and_bucket
        getattr(self, bucket).append(event.payload)
        return True

    def clear(self) -> None:
        """Очистить все накопители."""
        self.orders.clear()
        self.subscriptions.clear()
        self.downloads.clear()
        self.clicks.clear()
        self.reviews.clear()

    def sales_rows(self) -> list[list[Any]]:
        """Строки ``mart_sales_daily`` из заказов, подписок, скачиваний и кликов."""
        return build_sales_rows(
            self.orders,
            self.downloads,
            subscriptions=self.subscriptions,
            clicks=self.clicks,
        )

    def sentiment_rows(self) -> list[list[Any]]:
        """Строки ``mart_sentiment_daily`` из отзывов."""
        return build_sentiment_rows(self.reviews)


__all__ = [
    "COMMERCE_TOPICS",
    "SALES_TOPICS",
    "SENTIMENT_TOPICS",
    "CommerceBatch",
    "CommerceEvent",
    "parse_commerce_event",
]
