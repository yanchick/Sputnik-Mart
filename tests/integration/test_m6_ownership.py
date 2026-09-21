"""Интеграционные тесты M6/m12: владение данными и жизненный цикл заказа.

Проверяют, что межсервисные обращения идут через API владельца, а заказ
проходит достижимые состояния ``ORDER_PENDING → ORDER_PAID → ORDER_FULFILLED``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from config import AppSettings, Settings
from support import (
    DEMO_DATASET,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    Apps,
    auth_header,
    build_apps,
    login,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def manual_pay_apps(session_factory: object) -> AsyncIterator[Apps]:
    """Стенд с выключенной демо-автооплатой: заказ остаётся ``ORDER_PENDING``."""
    built = build_apps(
        session_factory,  # type: ignore[arg-type]
        Settings(app=AppSettings(demo_auto_pay=False)),
    )
    try:
        yield built
    finally:
        await built.gateway_client.aclose()
        await built.peer_client.aclose()


async def test_order_price_is_read_from_catalog_owner(apps: Apps) -> None:
    """M6: сумма заказа берётся из catalog-API, а не из чужой таблицы."""
    client = apps.gateway_client
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    headers = auth_header(login_response.json()["accessToken"])

    card = await client.get(f"/api/v1/datasets/{DEMO_DATASET}", headers=headers)
    assert card.status_code == 200
    price = card.json()["pricePerUnit"]

    order = await client.post(
        "/api/v1/orders",
        json={"datasetId": DEMO_DATASET},
        headers={**headers, "Idempotency-Key": "m6-owner-price-1"},
    )
    assert order.status_code == 201
    assert order.json()["status"] == "ORDER_PAID"
    assert order.json()["amount"] == pytest.approx(price)


async def test_identity_lists_subscriptions_via_order(apps: Apps) -> None:
    """M6: identity отдаёт подписки из order-сервиса, а не из orders.subscriptions."""
    client = apps.gateway_client
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    token = login_response.json()["accessToken"]
    headers = auth_header(token)

    me = await client.get("/api/v1/users/me", headers=headers)
    user_id = me.json()["userId"]

    created = await client.post(
        "/api/v1/subscriptions",
        json={"datasetId": DEMO_DATASET, "intervalSec": 300},
        headers=headers,
    )
    assert created.status_code == 201

    subscriptions = await client.get(f"/api/v1/users/{user_id}/subscriptions", headers=headers)
    assert subscriptions.status_code == 200
    assert any(
        item["subscriptionId"] == created.json()["subscriptionId"]
        for item in subscriptions.json()["data"]
    )


async def test_order_lifecycle_pending_paid_fulfilled(manual_pay_apps: Apps) -> None:
    """m12: PENDING → PAID → FULFILLED и запрет скачивания до оплаты."""
    client = manual_pay_apps.gateway_client
    token = await login(client)
    headers = auth_header(token)
    dataset = "ds_energy-consumption"

    created = await client.post(
        "/api/v1/orders",
        json={"datasetId": dataset},
        headers={**headers, "Idempotency-Key": "m12-lifecycle-1"},
    )
    assert created.status_code == 201
    order_id = created.json()["orderId"]
    assert created.json()["status"] == "ORDER_PENDING"

    denied = await client.get(
        f"/api/v1/datasets/{dataset}/download", params={"format": "CSV"}, headers=headers
    )
    assert denied.status_code == 403

    paid = await client.post(f"/api/v1/orders/{order_id}/pay", headers=headers)
    assert paid.status_code == 200
    assert paid.json()["status"] == "ORDER_PAID"

    downloaded = await client.get(
        f"/api/v1/datasets/{dataset}/download", params={"format": "CSV"}, headers=headers
    )
    assert downloaded.status_code == 200

    listing = await client.get("/api/v1/orders", headers=headers)
    match = next(item for item in listing.json()["data"] if item["orderId"] == order_id)
    assert match["status"] == "ORDER_FULFILLED"


async def test_order_pay_enforces_ownership(apps: Apps) -> None:
    """M6/m12: чужой заказ нельзя оплатить — 403."""
    client = apps.gateway_client
    buyer = await login(client)
    created = await client.post(
        "/api/v1/orders",
        json={"datasetId": DEMO_DATASET},
        headers={**auth_header(buyer), "Idempotency-Key": "m12-ownership-1"},
    )
    assert created.status_code == 201

    analyst = await login(client, "analyst@sputnik.demo")
    forbidden = await client.post(
        f"/api/v1/orders/{created.json()['orderId']}/pay",
        headers=auth_header(analyst),
    )
    assert forbidden.status_code == 403


async def test_identity_subscriptions_enforce_self(apps: Apps) -> None:
    """M6: подписки другого покупателя недоступны — 403."""
    client = apps.gateway_client
    buyer = await login(client)
    me = await client.get("/api/v1/users/me", headers=auth_header(buyer))
    buyer_id = me.json()["userId"]

    analyst = await login(client, "analyst@sputnik.demo")
    forbidden = await client.get(
        f"/api/v1/users/{buyer_id}/subscriptions", headers=auth_header(analyst)
    )
    assert forbidden.status_code == 403


async def test_review_text_is_scrubbed_end_to_end(apps: Apps) -> None:
    """m8: PII в отзыве не сохраняется и не отдаётся из БД."""
    client = apps.gateway_client
    token = await login(client)
    headers = auth_header(token)

    created = await client.post(
        "/api/v1/reviews",
        json={
            "datasetId": "ds_retail-sales",
            "rating": 5,
            "text": "пишите buyer@sputnik.demo или +79261234567",
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert "buyer@sputnik.demo" not in created.json()["text"]

    listing = await client.get(
        "/api/v1/reviews",
        params={"datasetId": "ds_retail-sales"},
        headers=headers,
    )
    stored = next(
        item for item in listing.json()["data"] if item["reviewId"] == created.json()["reviewId"]
    )
    assert "buyer@sputnik.demo" not in stored["text"]
    assert "+79261234567" not in stored["text"]
