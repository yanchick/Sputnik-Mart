"""Schemathesis-сьют против живого quality-service (M5, FR-031).

Схема ``openapi-quality.yaml`` поднимается как ASGI-приложение поверх реальной
Postgres (testcontainers): read-only срез качества отдаёт реальный каталог, а
операторский ``POST /quality/recalculate`` без токена отклоняется 401 — оба
исхода описаны в контракте.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from quality.main import create_app as create_quality_app
from support import client_for, load_openapi

pytestmark = pytest.mark.contract

quality_schema = load_openapi("openapi-quality.yaml")
# GET /quality/recalculate перехватывается параметрическим GET /quality/{datasetId}
# и отдаёт 404 (легитимный срез), а не 405: проверка «неподдерживаемых методов»
# неприменима к перекрытию путей.
quality_schema.config.checks.unsupported_method.enabled = False


class _StubIdentity:
    """Заглушка identity: любой машинный ключ недействителен (M6)."""

    async def get_json(self, path: str, **kwargs: object) -> dict[str, object]:
        return {}

    async def post_json(self, path: str, **kwargs: object) -> dict[str, object]:
        return {"userId": None}


@pytest.fixture
async def quality_app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    """Живой quality-service поверх общей тестовой БД."""
    return create_quality_app(
        settings=Settings(),
        session_factory=session_factory,
        identity_client=_StubIdentity(),
    )


@pytest.fixture(autouse=True)
async def _wire(quality_app: FastAPI) -> None:
    quality_schema.app = quality_app


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@quality_schema.parametrize()
def test_schemathesis_quality_live(case: object) -> None:
    """Живой quality-service отвечает по схеме OpenAPI."""
    client = asgi.get_client(quality_schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_quality_serves_openapi(quality_app: FastAPI) -> None:
    """quality-service отдаёт собственную OpenAPI-схему для машинной проверки."""
    async with client_for(quality_app) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")
