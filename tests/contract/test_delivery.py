"""Контрактный тест delivery: отказ 403 без оплаты и форматы выгрузки (T059)."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi

from support import DEMO_DATASET, Apps, auth_header, client_for, load_openapi, token_for

pytestmark = pytest.mark.contract

schema = load_openapi("openapi-delivery.yaml")
DEMO_API_KEY = "sk_demo_buyer_key"


@pytest.fixture(autouse=True)
async def _wire(apps: Apps) -> None:
    schema.app = apps.delivery


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@schema.parametrize()
def test_delivery_contract(case: object) -> None:
    """Schemathesis сверяет ответы delivery-сервиса с OpenAPI-контрактом."""
    client = asgi.get_client(schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_download_forbidden_without_payment(apps: Apps) -> None:
    """Без оплаченного заказа выгрузка запрещена (FR-007)."""
    async with client_for(apps.delivery) as client:
        token = await token_for(apps)
        response = await client.get(
            "/api/v1/datasets/ds_energy-consumption/download",
            headers=auth_header(token),
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_download_allowed_after_payment_and_by_api_key(apps: Apps) -> None:
    """После оплаты выгрузка отдаётся, в том числе по X-Api-Key (FR-036)."""
    async with client_for(apps.order) as order_client:
        token = await token_for(apps)
        created = await order_client.post(
            "/api/v1/orders",
            json={"datasetId": DEMO_DATASET},
            headers={**auth_header(token), "Idempotency-Key": "delivery-payment"},
        )
        assert created.status_code == 201

    async with client_for(apps.delivery) as delivery_client:
        bearer = await delivery_client.get(
            "/api/v1/datasets/ds_weather-stations/download",
            params={"format": "JSON"},
            headers=auth_header(token),
        )
        assert bearer.status_code == 200
        assert bearer.headers["content-type"].startswith("application/json")

        by_key = await delivery_client.get(
            "/api/v1/datasets/ds_weather-stations/download",
            headers={"X-Api-Key": DEMO_API_KEY},
        )
        assert by_key.status_code == 200
