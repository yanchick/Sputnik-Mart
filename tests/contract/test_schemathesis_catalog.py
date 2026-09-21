"""Schemathesis-сьют против живых сервисов catalog/order (T160, FR-031).

Схема поднимается в процесс теста как настоящее ASGI-приложение поверх реальной
Postgres (testcontainers): schemathesis вызывает живые эндпоинты и сверяет
ответы с OpenAPI-контрактами.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi

from support import Apps, client_for, load_openapi

pytestmark = pytest.mark.contract

catalog_schema = load_openapi("openapi-catalog.yaml")
order_schema = load_openapi("openapi-order.yaml")


@pytest.fixture(autouse=True)
async def _wire(apps: Apps) -> None:
    catalog_schema.app = apps.catalog
    order_schema.app = apps.order


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@catalog_schema.parametrize()
def test_schemathesis_catalog_live(case: object) -> None:
    """Живой catalog отвечает по схеме OpenAPI."""
    client = asgi.get_client(catalog_schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@order_schema.parametrize()
def test_schemathesis_order_live(case: object) -> None:
    """Живой order отвечает по схеме OpenAPI."""
    client = asgi.get_client(order_schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_live_openapi_is_served(apps: Apps) -> None:
    """Сервисы отдают собственные OpenAPI-схемы для машинной проверки."""
    async with client_for(apps.catalog) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")
