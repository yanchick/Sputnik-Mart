"""Контрактный тест catalog: listDatasets, getDataset, schema, sample (T057)."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, settings
from schemathesis.python import asgi

from support import Apps, auth_header, client_for, load_openapi, token_for

pytestmark = pytest.mark.contract

schema = load_openapi("openapi-catalog.yaml")


@pytest.fixture(autouse=True)
async def _wire(apps: Apps) -> None:
    schema.app = apps.catalog


@settings(
    max_examples=5, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@schema.parametrize()
def test_catalog_contract(case: object) -> None:
    """Schemathesis сверяет ответы catalog с OpenAPI-контрактом."""
    client = asgi.get_client(schema.app)
    with client:
        case.call_and_validate(session=client)  # type: ignore[attr-defined]


async def test_catalog_positive_and_formats(apps: Apps) -> None:
    """Позитивный путь: карточка, схема и образцы CSV/JSON/PARQUET."""
    async with client_for(apps.catalog) as client:
        token = await token_for(apps)
        headers = auth_header(token)

        listing = await client.get("/api/v1/datasets", headers=headers)
        assert listing.status_code == 200
        pagination = listing.json()["pagination"]
        assert set(pagination) == {"page", "pageSize", "total", "totalPages", "hasMore"}

        card = await client.get("/api/v1/datasets/ds_weather-stations", headers=headers)
        assert card.status_code == 200
        assert card.json()["category"] == "WEATHER"

        schema_response = await client.get(
            "/api/v1/datasets/ds_weather-stations/schema", headers=headers
        )
        assert schema_response.status_code == 200
        assert schema_response.json()

        csv_sample = await client.get(
            "/api/v1/datasets/ds_weather-stations/sample", headers=headers
        )
        assert csv_sample.status_code == 200
        assert csv_sample.headers["content-type"].startswith("text/csv")

        parquet_sample = await client.get(
            "/api/v1/datasets/ds_weather-stations/sample",
            params={"format": "PARQUET"},
            headers=headers,
        )
        assert parquet_sample.status_code == 200
        assert parquet_sample.content[:4] == b"PAR1"


async def test_catalog_requires_auth(apps: Apps) -> None:
    """Без Bearer-токена каталог отвечает 401 в едином конверте (FR-034)."""
    async with client_for(apps.catalog) as client:
        response = await client.get("/api/v1/datasets")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert "requestId" in response.json()["error"]


async def test_catalog_filters_and_pagination(apps: Apps) -> None:
    """Фильтры category/minQuality и единый формат пагинации (FR-003)."""
    async with client_for(apps.catalog) as client:
        token = await token_for(apps)
        headers = auth_header(token)

        filtered = await client.get(
            "/api/v1/datasets",
            params={"category": "ENERGY", "minQuality": 0.0, "pageSize": 1, "page": 1},
            headers=headers,
        )
        assert filtered.status_code == 200
        body = filtered.json()
        assert len(body["data"]) <= 1
        assert all(item["category"] == "ENERGY" for item in body["data"])

        invalid = await client.get(
            "/api/v1/datasets",
            params={"minQuality": 2},
            headers=headers,
        )
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
