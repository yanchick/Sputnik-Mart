"""Schemathesis-сьют против живого review: отзывы и рейтинг (M5, FR-031).

Схема ``openapi-review.yaml`` поднимается как ASGI-приложение поверх реальной
Postgres (testcontainers). Анонимные запросы отклоняются 401 в едином конверте,
что и описывает контракт.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi

from support import Apps, client_for, load_openapi

pytestmark = pytest.mark.contract

review_schema = load_openapi("openapi-review.yaml")


@pytest.fixture(autouse=True)
async def _wire(apps: Apps) -> None:
    review_schema.app = apps.review


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@review_schema.parametrize()
def test_schemathesis_review_live(case: object) -> None:
    """Живой review отвечает по схеме OpenAPI."""
    client = asgi.get_client(review_schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_review_serves_openapi(apps: Apps) -> None:
    """review отдаёт собственную OpenAPI-схему для машинной проверки."""
    async with client_for(apps.review) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")
