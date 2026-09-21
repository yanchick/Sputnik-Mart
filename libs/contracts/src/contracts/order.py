"""Pydantic v2-модели заказов и подписок из ``openapi-order.yaml``."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .common import (
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    PagedResponse,
    Pagination,
)

DATASET_ID_PATTERN = r"^ds_[a-z0-9_-]+$"


class OrderStatus(StrEnum):
    """Состояния заказа (``OrderStatus``)."""

    ORDER_PENDING = "ORDER_PENDING"
    ORDER_PAID = "ORDER_PAID"
    ORDER_FULFILLED = "ORDER_FULFILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class SubscriptionStatus(StrEnum):
    """Состояния подписки (``SubscriptionStatus``)."""

    SUB_ACTIVE = "SUB_ACTIVE"
    SUB_PAUSED = "SUB_PAUSED"
    SUB_CANCELLED = "SUB_CANCELLED"


class CreateOrderRequest(BaseModel):
    """Тело запроса ``createOrder`` (``CreateOrderRequest``)."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str = Field(pattern=DATASET_ID_PATTERN)
    quantity: int = Field(default=1, ge=1)


class CreateSubscriptionRequest(BaseModel):
    """Тело запроса ``createSubscription`` (``CreateSubscriptionRequest``)."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str = Field(pattern=DATASET_ID_PATTERN)
    intervalSec: int = Field(ge=60, le=86400)


class FulfillOrderRequest(BaseModel):
    """Тело запроса выдачи данных по оплаченному заказу (m12)."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str = Field(pattern=DATASET_ID_PATTERN)


class OrderAccess(BaseModel):
    """Ответ проверки права скачивания датасета (FR-007, M6)."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str = Field(pattern=DATASET_ID_PATTERN)
    hasAccess: bool


class Order(BaseModel):
    """Заказ покупателя (``Order``)."""

    model_config = ConfigDict(extra="forbid")

    orderId: str
    userId: str
    datasetId: str
    status: OrderStatus
    createdAt: datetime
    amount: float | None = None


class Subscription(BaseModel):
    """Подписка на поток данных (``Subscription``)."""

    model_config = ConfigDict(extra="forbid")

    subscriptionId: str
    userId: str
    datasetId: str
    intervalSec: int = Field(gt=0)
    status: SubscriptionStatus
    startedAt: datetime


type PagedOrders = PagedResponse[Order | Subscription]

__all__ = [
    "DATASET_ID_PATTERN",
    "CreateOrderRequest",
    "CreateSubscriptionRequest",
    "ErrorBody",
    "ErrorDetail",
    "ErrorEnvelope",
    "FulfillOrderRequest",
    "Order",
    "OrderAccess",
    "OrderStatus",
    "PagedOrders",
    "PagedResponse",
    "Pagination",
    "Subscription",
    "SubscriptionStatus",
]
