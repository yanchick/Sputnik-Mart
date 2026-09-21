"""Семантика статусов заказа (m12, переходы из ``data-model.md``).

Допустимые переходы:

* ``ORDER_PENDING → ORDER_PAID`` — успешная оплата;
* ``ORDER_PENDING → ORDER_CANCELLED`` — отмена до оплаты;
* ``ORDER_PAID → ORDER_FULFILLED`` — данные выданы покупателю.

Оплата идемпотентна: повтор ``PAY`` на уже оплаченном заказе сохраняет
``ORDER_PAID``.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from contracts import OrderStatus

from . import repository as repo


class OrderAction(StrEnum):
    """Действие над заказом."""

    PAY = "PAY"
    CANCEL = "CANCEL"
    FULFILL = "FULFILL"


class OrderStateError(ValueError):
    """Недопустимый переход статуса заказа."""


_TRANSITIONS: dict[tuple[str, OrderAction], OrderStatus] = {
    (OrderStatus.ORDER_PENDING.value, OrderAction.PAY): OrderStatus.ORDER_PAID,
    (OrderStatus.ORDER_PENDING.value, OrderAction.CANCEL): OrderStatus.ORDER_CANCELLED,
    (OrderStatus.ORDER_PAID.value, OrderAction.FULFILL): OrderStatus.ORDER_FULFILLED,
    (OrderStatus.ORDER_PAID.value, OrderAction.PAY): OrderStatus.ORDER_PAID,
    (OrderStatus.ORDER_FULFILLED.value, OrderAction.PAY): OrderStatus.ORDER_FULFILLED,
    (OrderStatus.ORDER_FULFILLED.value, OrderAction.FULFILL): OrderStatus.ORDER_FULFILLED,
}


def next_status(current: str, action: OrderAction) -> OrderStatus:
    """Вернуть новый статус или упасть с :class:`OrderStateError`."""
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise OrderStateError(f"Переход {current} --{action.value}--> недопустим для заказа")
    return target


def is_paid(status: str) -> bool:
    """Скачивание разрешено при ``ORDER_PAID`` и ``ORDER_FULFILLED`` (FR-007)."""
    return status in (OrderStatus.ORDER_PAID.value, OrderStatus.ORDER_FULFILLED.value)


async def apply_transition(
    session: AsyncSession,
    order: repo.Order,
    action: OrderAction,
) -> repo.Order:
    """Применить переход к заказу и зафиксировать новое состояние."""
    order.status = next_status(order.status, action).value
    session.add(order)
    await session.flush()
    return order


__all__ = [
    "OrderAction",
    "OrderStateError",
    "apply_transition",
    "is_paid",
    "next_status",
]
