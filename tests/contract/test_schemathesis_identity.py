"""Schemathesis-сьют против живого identity: login, профиль, ключи (M5, FR-031).

Схема ``openapi-identity.yaml`` поднимается в процесс теста как настоящее
ASGI-приложение поверх реальной Postgres (testcontainers), а schemathesis
сверяет ответы с контрактом. Анонимные запросы ожидаемо получают 401 из
единого конверта — это задокументировано в схеме.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi

from support import Apps, client_for, load_openapi

pytestmark = pytest.mark.contract

identity_schema = load_openapi("openapi-identity.yaml")


@pytest.fixture(autouse=True)
async def _wire(apps: Apps) -> None:
    identity_schema.app = apps.identity


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@identity_schema.parametrize()
def test_schemathesis_identity_live(case: object) -> None:
    """Живой identity отвечает по схеме OpenAPI."""
    client = asgi.get_client(identity_schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_identity_serves_openapi(apps: Apps) -> None:
    """identity отдаёт собственную OpenAPI-схему для машинной проверки."""
    async with client_for(apps.identity) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")
