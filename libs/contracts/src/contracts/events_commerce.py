"""Конверт и payload-ы бизнес-событий commerce из ``asyncapi-commerce.yaml``.

Машинный wire-формат — плоский (``EventEnvelope`` через ``allOf``): поля топика
лежат в корне сообщения рядом с ``eventId``/``userId``/``at``. Описательный
конверт ``BusinessEvent`` из data-model также доступен для читаемости.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import FileFormat


class CommerceTopic(StrEnum):
    """Имена топиков бизнес-событий."""

    CLICKS = "commerce.clicks"
    ORDERS = "commerce.orders"
    SUBSCRIPTIONS = "commerce.subscriptions"
    DOWNLOADS = "commerce.downloads"
    REVIEWS = "commerce.reviews"


class ClickSource(StrEnum):
    """Источник клика по продукту."""

    STORE = "STORE"
    SAMPLE = "SAMPLE"
    DOCS = "DOCS"


class EventEnvelope(BaseModel):
    """Общая часть всех commerce-событий (``EventEnvelope``)."""

    model_config = ConfigDict(extra="forbid")

    eventId: str
    userId: str
    at: datetime


class ClickEventPayload(EventEnvelope):
    """Событие ``commerce.clicks``."""

    datasetId: str
    source: ClickSource


class OrderEventPayload(EventEnvelope):
    """Событие ``commerce.orders``."""

    orderId: str
    datasetId: str
    amount: float


class SubscriptionEventPayload(EventEnvelope):
    """Событие ``commerce.subscriptions``."""

    subscriptionId: str
    datasetId: str
    intervalSec: int = Field(gt=0)


class DownloadEventPayload(EventEnvelope):
    """Событие ``commerce.downloads``."""

    downloadId: str
    datasetId: str
    format: FileFormat


class ReviewEventPayload(EventEnvelope):
    """Событие ``commerce.reviews``."""

    reviewId: str
    datasetId: str
    rating: int = Field(ge=1, le=5)
    text: str


class ProductKind(StrEnum):
    """Тип продукта в описательной ссылке ``productRef``."""

    DATASET = "DATASET"


class ProductRef(BaseModel):
    """Описательная ссылка на продукт (``productRef`` из data-model)."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str
    kind: ProductKind = ProductKind.DATASET


class BusinessEvent(BaseModel):
    """Описательный конверт ``{eventId,userId,productRef,at,payload}``.

    Не является wire-форматом конкретного топика: машинные payload-ы лежат в
    :class:`ClickEventPayload` и родственных классах.
    """

    model_config = ConfigDict(extra="forbid")

    eventId: str
    userId: str
    productRef: ProductRef
    at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BusinessEvent",
    "ClickEventPayload",
    "ClickSource",
    "CommerceTopic",
    "DownloadEventPayload",
    "EventEnvelope",
    "OrderEventPayload",
    "ProductKind",
    "ProductRef",
    "ReviewEventPayload",
    "SubscriptionEventPayload",
]
