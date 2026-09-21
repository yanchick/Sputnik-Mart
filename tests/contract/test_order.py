"""Контрактный тест order: createOrder, listOrders, подписки (T058)."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi

from support import DEMO_DATASET, Apps, auth_header, client_for, load_openapi, token_for

pytestmark = pytest.mark.contract

schema = load_openapi("openapi-order.yaml")


@pytest.fixture(autouse=True)
async def _wire(apps: Apps) -> None:
    schema.app = apps.order


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@schema.parametrize()
def test_order_contract(case: object) -> None:
    """Schemathesis сверяет ответы order-сервиса с OpenAPI-контрактом."""
    client = asgi.get_client(schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_order_idempotent_and_listed(apps: Apps) -> None:
    """Повтор с тем же Idempotency-Key не создаёт новый заказ (FR-006)."""
    async with client_for(apps.order) as client:
        token = await token_for(apps)
        headers = {**auth_header(token), "Idempotency-Key": "contract-order-1"}
        body = {"datasetId": DEMO_DATASET}

        first = await client.post("/api/v1/orders", json=body, headers=headers)
        second = await client.post("/api/v1/orders", json=body, headers=headers)
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["orderId"] == second.json()["orderId"]
        assert first.json()["status"] == "ORDER_PAID"
        assert len(apps.order_events.published) >= 1

        listing = await client.get("/api/v1/orders", headers=auth_header(token))
        assert listing.status_code == 200
        assert listing.json()["pagination"]["total"] >= 1


async def test_subscription_created(apps: Apps) -> None:
    """Оформление подписки возвращает SUB_ACTIVE и публикует событие."""
    async with client_for(apps.order) as client:
        token = await token_for(apps)
        response = await client.post(
            "/api/v1/subscriptions",
            json={"datasetId": DEMO_DATASET, "intervalSec": 300},
            headers=auth_header(token),
        )
    assert response.status_code == 201
    assert response.json()["status"] == "SUB_ACTIVE"
    assert response.json()["intervalSec"] == 300
