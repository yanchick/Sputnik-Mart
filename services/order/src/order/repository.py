"""Репозитории заказов, подписок и скачиваний (T077).

Инвариант ``UNIQUE (user_id, idempotency_key)`` обеспечивается миграцией 0003.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from db.postgres import Base

ORDER_STATUS_PENDING = "ORDER_PENDING"
ORDER_STATUS_PAID = "ORDER_PAID"
ORDER_STATUS_FULFILLED = "ORDER_FULFILLED"
SUBSCRIPTION_STATUS_ACTIVE = "SUB_ACTIVE"
DOWNLOAD_STATUS_REQUESTED = "REQUESTED"


class Order(Base):
    """Заказ покупателя (``orders.orders``)."""

    __tablename__ = "orders"
    __table_args__ = {"schema": "orders"}

    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    status: Mapped[str] = mapped_column(Text, nullable=False, default=ORDER_STATUS_PENDING)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class Subscription(Base):
    """Подписка на поток данных (``orders.subscriptions``)."""

    __tablename__ = "subscriptions"
    __table_args__ = {"schema": "orders"}

    subscription_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    interval_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=SUBSCRIPTION_STATUS_ACTIVE)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Download(Base):
    """Факт выгрузки датасета (``orders.downloads``)."""

    __tablename__ = "downloads"
    __table_args__ = {"schema": "orders"}

    download_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=DOWNLOAD_STATUS_REQUESTED)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


async def get_order_by_idempotency(
    session: AsyncSession, user_id: str, idempotency_key: str
) -> Order | None:
    """Найти заказ по ключу идемпотентности покупателя."""
    statement = select(Order).where(
        Order.user_id == user_id, Order.idempotency_key == idempotency_key
    )
    return (await session.execute(statement)).scalars().first()


async def get_order(session: AsyncSession, order_id: str) -> Order | None:
    """Найти заказ по идентификатору."""
    return await session.get(Order, order_id)


async def add_order(session: AsyncSession, order: Order) -> Order:
    """Добавить заказ и зафиксировать его в текущей транзакции."""
    session.add(order)
    await session.flush()
    return order


async def list_orders(
    session: AsyncSession, user_id: str, *, page: int, page_size: int
) -> tuple[list[Order], int]:
    """Постранично вернуть заказы покупателя (свежие первыми)."""
    conditions = [Order.user_id == user_id]
    total = int(
        (
            await session.execute(select(func.count()).select_from(Order).where(*conditions))
        ).scalar_one()
    )
    statement = (
        select(Order)
        .where(*conditions)
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await session.execute(statement)).scalars().all()), total


async def list_downloads(
    session: AsyncSession, user_id: str, *, page: int, page_size: int
) -> tuple[list[Download], int]:
    """Постранично вернуть историю скачиваний покупателя."""
    conditions = [Download.user_id == user_id]
    total = int(
        (
            await session.execute(select(func.count()).select_from(Download).where(*conditions))
        ).scalar_one()
    )
    statement = (
        select(Download)
        .where(*conditions)
        .order_by(Download.requested_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await session.execute(statement)).scalars().all()), total


async def add_subscription(session: AsyncSession, subscription: Subscription) -> Subscription:
    """Оформить подписку."""
    session.add(subscription)
    await session.flush()
    return subscription


async def list_subscriptions(session: AsyncSession, user_id: str) -> list[Subscription]:
    """Вернуть подписки покупателя."""
    statement = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.started_at.desc())
    )
    return list((await session.execute(statement)).scalars().all())


async def get_subscription(session: AsyncSession, subscription_id: str) -> Subscription | None:
    """Найти подписку по идентификатору."""
    return await session.get(Subscription, subscription_id)


async def find_paid_order(session: AsyncSession, user_id: str, dataset_id: str) -> Order | None:
    """Найти оплаченный/исполненный заказ покупателя на датасет (M6, m12)."""
    statement = (
        select(Order)
        .where(
            Order.user_id == user_id,
            Order.dataset_id == dataset_id,
            Order.status.in_((ORDER_STATUS_PAID, ORDER_STATUS_FULFILLED)),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def has_paid_order(session: AsyncSession, user_id: str, dataset_id: str) -> bool:
    """Есть ли у покупателя оплаченный или исполненный заказ на датасет."""
    statement = text("""
        SELECT 1 FROM orders.orders
        WHERE user_id = :user_id AND dataset_id = :dataset_id
          AND status IN ('ORDER_PAID', 'ORDER_FULFILLED')
        LIMIT 1
        """)
    row = (await session.execute(statement, {"user_id": user_id, "dataset_id": dataset_id})).first()
    return row is not None


__all__ = [
    "DOWNLOAD_STATUS_REQUESTED",
    "ORDER_STATUS_FULFILLED",
    "ORDER_STATUS_PAID",
    "ORDER_STATUS_PENDING",
    "SUBSCRIPTION_STATUS_ACTIVE",
    "Download",
    "Order",
    "Subscription",
    "add_order",
    "add_subscription",
    "find_paid_order",
    "get_order",
    "get_order_by_idempotency",
    "get_subscription",
    "has_paid_order",
    "list_downloads",
    "list_orders",
    "list_subscriptions",
]
