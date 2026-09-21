"""Семантика статусов подписки (T145, FR-009).

Допустимые переходы:

* ``SUB_ACTIVE → SUB_PAUSED`` — остановить живой поток и выборку новых данных,
  сохранив подписку и доступ к купленным данным;
* ``SUB_PAUSED → SUB_ACTIVE`` — возобновить доставку без дублей;
* ``SUB_ACTIVE|SUB_PAUSED → SUB_CANCELLED`` — окончательно завершить подписку
  (``cancelled_at`` заполняется); ``SUB_CANCELLED`` терминален, но можно
  оформить новую подписку.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from contracts import SubscriptionStatus

from . import repository as repo


class SubscriptionAction(StrEnum):
    """Действие покупателя над подпиской."""

    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


class SubscriptionStateError(ValueError):
    """Недопустимый переход статуса подписки."""


_TRANSITIONS: dict[tuple[str, SubscriptionAction], SubscriptionStatus] = {
    (SubscriptionStatus.SUB_ACTIVE.value, SubscriptionAction.PAUSE): SubscriptionStatus.SUB_PAUSED,
    (SubscriptionStatus.SUB_PAUSED.value, SubscriptionAction.RESUME): SubscriptionStatus.SUB_ACTIVE,
    (SubscriptionStatus.SUB_ACTIVE.value, SubscriptionAction.CANCEL): (
        SubscriptionStatus.SUB_CANCELLED
    ),
    (SubscriptionStatus.SUB_PAUSED.value, SubscriptionAction.CANCEL): (
        SubscriptionStatus.SUB_CANCELLED
    ),
}


def next_status(current: str, action: SubscriptionAction) -> SubscriptionStatus:
    """Вернуть новый статус или упасть с :class:`SubscriptionStateError`."""
    target = _TRANSITIONS.get((current, action))
    if target is None:
        raise SubscriptionStateError(
            f"Переход {current} --{action.value}--> недопустим для подписки"
        )
    return target


def is_terminal(status: str) -> bool:
    """``SUB_CANCELLED`` — терминальное состояние подписки."""
    return status == SubscriptionStatus.SUB_CANCELLED.value


def is_streaming(status: str) -> bool:
    """Только ``SUB_ACTIVE`` допускает живой поток и выборку новых данных."""
    return status == SubscriptionStatus.SUB_ACTIVE.value


async def apply_transition(
    session: AsyncSession,
    subscription: repo.Subscription,
    action: SubscriptionAction,
    *,
    now: datetime | None = None,
) -> repo.Subscription:
    """Применить переход к подписке и зафиксировать ``cancelled_at``."""
    target = next_status(subscription.status, action)
    subscription.status = target.value
    if target is SubscriptionStatus.SUB_CANCELLED:
        subscription.cancelled_at = now or datetime.now(UTC)
    session.add(subscription)
    await session.flush()
    return subscription


__all__ = [
    "SubscriptionAction",
    "SubscriptionStateError",
    "apply_transition",
    "is_streaming",
    "is_terminal",
    "next_status",
]
