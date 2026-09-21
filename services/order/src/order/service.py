"""Сервис заказов и подписок с идемпотентностью (T078, m12, M6)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import Order as OrderContract
from contracts import Subscription as SubscriptionContract
from observability import USER_ID_HEADER, ApiError
from service_client import ServiceClient

from . import repository as repo
from .events import EventPublisher, publish_order, publish_subscription
from .order_states import OrderAction, apply_transition
from .subscription_states import (
    SubscriptionAction,
    SubscriptionStateError,
)
from .subscription_states import (
    apply_transition as sub_transition,
)

DEFAULT_PRICE = Decimal("0")


def to_order_contract(order: repo.Order) -> OrderContract:
    """Преобразовать ORM-заказ в контракт."""
    return OrderContract(
        orderId=order.order_id,
        userId=order.user_id,
        datasetId=order.dataset_id,
        status=order.status,
        createdAt=order.created_at,
        amount=float(order.amount),
    )


def to_subscription_contract(subscription: repo.Subscription) -> SubscriptionContract:
    """Преобразовать ORM-подписку в контракт."""
    return SubscriptionContract(
        subscriptionId=subscription.subscription_id,
        userId=subscription.user_id,
        datasetId=subscription.dataset_id,
        intervalSec=subscription.interval_sec,
        status=subscription.status,
        startedAt=subscription.started_at,
    )


async def catalog_price(catalog: ServiceClient, dataset_id: str, user_id: str) -> Decimal | None:
    """Цена датасета из catalog-сервиса — владельца каталога (M6).

    ``None`` означает, что датасет не найден (404 владельца).
    """
    try:
        payload = await catalog.get_json(
            f"/api/v1/datasets/{dataset_id}", headers={USER_ID_HEADER: user_id}
        )
    except ApiError as error:
        if error.status_code == 404:
            return None
        raise
    value = payload.get("pricePerUnit") if isinstance(payload, Mapping) else None
    return Decimal(str(value)) if value is not None else DEFAULT_PRICE


async def create_order(
    session: AsyncSession,
    publisher: EventPublisher,
    catalog: ServiceClient,
    *,
    user_id: str,
    dataset_id: str,
    quantity: int,
    idempotency_key: str,
    auto_pay: bool = False,
) -> tuple[repo.Order, bool]:
    """Создать заказ; при повторе ключа вернуть уже созданный (FR-006, m12).

    Заказ рождается в ``ORDER_PENDING``. Демо-профиль выполняет автооплату
    (``auto_pay``), после чего заказ сразу доступен к скачиванию; явный
    переход — ``POST /orders/{orderId}/pay``.
    """
    existing = await repo.get_order_by_idempotency(session, user_id, idempotency_key)
    if existing is not None:
        return existing, False

    price = await catalog_price(catalog, dataset_id, user_id)
    if price is None:
        raise ApiError(404, "NOT_FOUND", "Датасет не найден")

    order = repo.Order(
        order_id=f"od_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        dataset_id=dataset_id,
        amount=price * quantity,
        status=repo.ORDER_STATUS_PENDING,
        idempotency_key=idempotency_key,
    )
    try:
        await repo.add_order(session, order)
    except IntegrityError:
        await session.rollback()
        repeated = await repo.get_order_by_idempotency(session, user_id, idempotency_key)
        if repeated is None:
            raise ApiError(409, "CONFLICT", "Конфликт идемпотентности заказа") from None
        return repeated, False

    if auto_pay:
        await apply_transition(session, order, OrderAction.PAY)
    await publish_order(publisher, order, user_id)
    return order, True


async def pay_order(session: AsyncSession, *, user_id: str, order_id: str) -> repo.Order:
    """Оплатить заказ покупателя: ``ORDER_PENDING → ORDER_PAID`` (m12)."""
    order = await _get_owned_order(session, user_id, order_id)
    return await apply_transition(session, order, OrderAction.PAY)


async def fulfill_order(session: AsyncSession, *, user_id: str, dataset_id: str) -> repo.Order:
    """Отметить выдачу данных: ``ORDER_PAID → ORDER_FULFILLED`` (FR-007, m12)."""
    order = await repo.find_paid_order(session, user_id, dataset_id)
    if order is None:
        raise ApiError(404, "NOT_FOUND", "Оплаченный заказ не найден")
    return await apply_transition(session, order, OrderAction.FULFILL)


async def has_download_access(session: AsyncSession, *, user_id: str, dataset_id: str) -> bool:
    """Есть ли право скачивания: оплаченный или исполненный заказ (FR-007)."""
    return await repo.has_paid_order(session, user_id, dataset_id)


async def _get_owned_order(session: AsyncSession, user_id: str, order_id: str) -> repo.Order:
    order = await repo.get_order(session, order_id)
    if order is None:
        raise ApiError(404, "NOT_FOUND", "Заказ не найден")
    if order.user_id != user_id:
        raise ApiError(403, "FORBIDDEN", "Заказ принадлежит другому покупателю")
    return order


async def list_orders(
    session: AsyncSession, user_id: str, *, page: int, page_size: int
) -> tuple[list[OrderContract], int]:
    """Список заказов покупателя с пагинацией."""
    orders, total = await repo.list_orders(session, user_id, page=page, page_size=page_size)
    return [to_order_contract(order) for order in orders], total


def to_download_payload(download: repo.Download) -> dict[str, object]:
    """Представление записи истории скачиваний."""
    return {
        "downloadId": download.download_id,
        "userId": download.user_id,
        "datasetId": download.dataset_id,
        "format": download.format,
        "bytes": download.bytes,
        "status": download.status,
        "requestedAt": download.requested_at.isoformat(),
    }


async def list_downloads(
    session: AsyncSession, user_id: str, *, page: int, page_size: int
) -> tuple[list[dict[str, object]], int]:
    """История скачиваний покупателя."""
    downloads, total = await repo.list_downloads(session, user_id, page=page, page_size=page_size)
    return [to_download_payload(download) for download in downloads], total


async def create_subscription(
    session: AsyncSession,
    publisher: EventPublisher,
    catalog: ServiceClient,
    *,
    user_id: str,
    dataset_id: str,
    interval_sec: int,
) -> repo.Subscription:
    """Оформить подписку на поток датасета (FR-009)."""
    if await catalog_price(catalog, dataset_id, user_id) is None:
        raise ApiError(404, "NOT_FOUND", "Датасет не найден")

    subscription = repo.Subscription(
        subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        dataset_id=dataset_id,
        interval_sec=interval_sec,
        status=repo.SUBSCRIPTION_STATUS_ACTIVE,
    )
    await repo.add_subscription(session, subscription)
    await publish_subscription(publisher, subscription, user_id)
    return subscription


async def list_subscriptions(session: AsyncSession, user_id: str) -> list[repo.Subscription]:
    """Вернуть подписки покупателя (используется identity через API, M6)."""
    return await repo.list_subscriptions(session, user_id)


async def get_subscription(session: AsyncSession, subscription_id: str) -> repo.Subscription:
    """Вернуть подписку по идентификатору или 404 (для delivery, M6)."""
    subscription = await repo.get_subscription(session, subscription_id)
    if subscription is None:
        raise ApiError(404, "NOT_FOUND", "Подписка не найдена")
    return subscription


async def change_subscription_state(
    session: AsyncSession,
    *,
    user_id: str,
    subscription_id: str,
    action: SubscriptionAction,
) -> repo.Subscription:
    """Применить действие покупателя к подписке (FR-009)."""
    subscription = await repo.get_subscription(session, subscription_id)
    if subscription is None:
        raise ApiError(404, "NOT_FOUND", "Подписка не найдена")
    if subscription.user_id != user_id:
        raise ApiError(403, "FORBIDDEN", "Подписка принадлежит другому покупателю")
    try:
        return await sub_transition(session, subscription, action)
    except SubscriptionStateError as error:
        raise ApiError(409, "CONFLICT", str(error)) from error


__all__ = [
    "catalog_price",
    "change_subscription_state",
    "create_order",
    "create_subscription",
    "fulfill_order",
    "get_subscription",
    "has_download_access",
    "list_downloads",
    "list_orders",
    "list_subscriptions",
    "pay_order",
    "to_download_payload",
    "to_order_contract",
    "to_subscription_contract",
]
