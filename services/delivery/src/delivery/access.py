"""Проверка права скачивания и машинной аутентификации (T084, FR-007, FR-036, M6).

Права и ключи принадлежат order- и identity-сервисам; delivery читает их
только по HTTP через общий клиент ``service_client``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from observability import USER_ID_HEADER, ApiError
from service_client import ServiceClient, resolve_api_key

PAID_STATUSES = ("ORDER_PAID", "ORDER_FULFILLED")


async def has_download_access(order: ServiceClient, user_id: str, dataset_id: str) -> bool:
    """Доступ к выгрузке есть только при оплаченном/исполненном заказе (FR-007)."""
    payload = await order.get_json(
        "/api/v1/orders/access",
        params={"datasetId": dataset_id},
        headers={USER_ID_HEADER: user_id},
    )
    access = payload.get("hasAccess") if isinstance(payload, Mapping) else None
    return bool(access)


async def user_id_for_api_key(identity: ServiceClient, api_key: str) -> str | None:
    """Разрешить машинный ключ в покупателя через identity (M6).

    Отозванный или неизвестный ключ даёт ``None``.
    """
    return await resolve_api_key(identity, api_key)


async def get_subscription(
    order: ServiceClient, subscription_id: str, user_id: str
) -> dict[str, Any] | None:
    """Вернуть подписку из order-сервиса в snake_case-виде или ``None`` (M6)."""
    try:
        payload = await order.get_json(
            f"/api/v1/subscriptions/{subscription_id}",
            headers={USER_ID_HEADER: user_id},
        )
    except ApiError as error:
        if error.status_code == 404:
            return None
        raise
    if not isinstance(payload, Mapping):
        return None
    return {
        "subscription_id": str(payload["subscriptionId"]),
        "user_id": str(payload["userId"]),
        "dataset_id": str(payload["datasetId"]),
        "status": str(payload["status"]),
    }


__all__ = [
    "PAID_STATUSES",
    "get_subscription",
    "has_download_access",
    "user_id_for_api_key",
]
