"""Unit-тесты order: события commerce.orders и контракты (T063)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from order.events import (
    NullPublisher,
    build_order_event,
    build_subscription_event,
    publish_order,
    publish_subscription,
)
from order.order_states import (
    OrderAction,
    OrderStateError,
    apply_transition,
    is_paid,
    next_status,
)
from order.repository import Order, Subscription
from order.service import to_order_contract, to_subscription_contract

from contracts import OrderStatus, SubscriptionStatus
from support import FakeAddSession

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _order(status: str = OrderStatus.ORDER_PAID.value) -> Order:
    return Order(
        order_id="od_1",
        user_id="us_1",
        dataset_id="ds_weather-stations",
        amount=Decimal("1200.00"),
        idempotency_key="key-1",
        status=status,
        created_at=NOW,
    )


def _subscription() -> Subscription:
    return Subscription(
        subscription_id="sub_1",
        user_id="us_1",
        dataset_id="ds_air-quality",
        interval_sec=300,
        status=SubscriptionStatus.SUB_ACTIVE.value,
        started_at=NOW,
    )


def test_order_contract_statuses() -> None:
    contract = to_order_contract(_order())

    assert contract.status is OrderStatus.ORDER_PAID
    assert contract.amount == 1200.0


def test_subscription_contract() -> None:
    contract = to_subscription_contract(_subscription())

    assert contract.status is SubscriptionStatus.SUB_ACTIVE
    assert contract.intervalSec == 300


def test_order_event_matches_asyncapi() -> None:
    event = build_order_event(_order(), "us_1")

    assert event["orderId"] == "od_1"
    assert event["datasetId"] == "ds_weather-stations"
    assert event["amount"] == 1200.0
    assert {"eventId", "userId", "at"} <= set(event)


def test_subscription_event_matches_asyncapi() -> None:
    event = build_subscription_event(_subscription(), "us_1")

    assert event["subscriptionId"] == "sub_1"
    assert event["intervalSec"] == 300


async def test_publish_records_to_topic() -> None:
    publisher = NullPublisher()

    await publish_order(publisher, _order(), "us_1")
    await publish_subscription(publisher, _subscription(), "us_1")

    topics = [topic for topic, _, _ in publisher.published]
    assert topics == ["commerce.orders", "commerce.subscriptions"]


def test_order_lifecycle_transitions_are_reachable() -> None:
    """m12: PENDING → PAID → FULFILLED и PENDING → CANCELLED разрешены."""
    assert next_status(OrderStatus.ORDER_PENDING.value, OrderAction.PAY) is OrderStatus.ORDER_PAID
    assert (
        next_status(OrderStatus.ORDER_PAID.value, OrderAction.FULFILL)
        is OrderStatus.ORDER_FULFILLED
    )
    assert (
        next_status(OrderStatus.ORDER_PENDING.value, OrderAction.CANCEL)
        is OrderStatus.ORDER_CANCELLED
    )


def test_order_pay_is_idempotent() -> None:
    """Повторная оплата не ломает уже оплаченный/исполненный заказ."""
    assert next_status(OrderStatus.ORDER_PAID.value, OrderAction.PAY) is OrderStatus.ORDER_PAID
    assert (
        next_status(OrderStatus.ORDER_FULFILLED.value, OrderAction.FULFILL)
        is OrderStatus.ORDER_FULFILLED
    )


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(OrderStateError):
        next_status(OrderStatus.ORDER_PENDING.value, OrderAction.FULFILL)
    with pytest.raises(OrderStateError):
        next_status(OrderStatus.ORDER_FULFILLED.value, OrderAction.CANCEL)


def test_is_paid_matches_download_rule() -> None:
    assert is_paid(OrderStatus.ORDER_PAID.value)
    assert is_paid(OrderStatus.ORDER_FULFILLED.value)
    assert not is_paid(OrderStatus.ORDER_PENDING.value)


async def test_apply_transition_mutates_and_flushes() -> None:
    session = FakeAddSession()
    order = _order(OrderStatus.ORDER_PENDING.value)

    result = await apply_transition(session, order, OrderAction.PAY)  # type: ignore[arg-type]

    assert result.status == OrderStatus.ORDER_PAID.value
    assert order in session.added


def test_pending_order_contract() -> None:
    contract = to_order_contract(_order(OrderStatus.ORDER_PENDING.value))

    assert contract.status is OrderStatus.ORDER_PENDING
    assert contract.amount == 1200.0
