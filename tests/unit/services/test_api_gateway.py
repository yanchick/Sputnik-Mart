"""Unit-тесты gateway: маршрут Quality-page и проброс заголовков (QR-2, QR-6)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from api_gateway.auth import issue_demo_token
from api_gateway.main import create_app, service_urls, upstream_for
from api_gateway.openapi import CONTRACT_FILES, load_gateway_openapi
from api_gateway.rate_limit import InMemoryRateLimiter

from config import AppSettings, Settings
from quality.main import create_app as create_quality_app

pytestmark = pytest.mark.unit

CONTRACT_DIR = (
    Path(__file__).resolve().parents[3] / "specs" / "001-sputnik-data-portal" / "contracts"
)


def test_gateway_openapi_merges_identity_review_quality() -> None:
    """M5: merged OpenAPI фасада содержит identity/review/quality-контракты."""
    spec = load_gateway_openapi(CONTRACT_DIR)

    assert {
        "openapi-catalog.yaml",
        "openapi-order.yaml",
        "openapi-delivery.yaml",
        "openapi-identity.yaml",
        "openapi-review.yaml",
        "openapi-quality.yaml",
    } <= set(CONTRACT_FILES)
    for path in (
        "/auth/login",
        "/users/me",
        "/users/{userId}/subscriptions",
        "/users/{userId}/api-keys",
        "/users/{userId}/api-keys/{keyId}",
        "/reviews",
        "/datasets/{datasetId}/rating",
        "/quality",
        "/quality/{datasetId}",
        "/quality/recalculate",
    ):
        assert path in spec["paths"], path


def test_upstream_for_routes_quality_paths() -> None:
    """QR-2: ``/api/v1/quality`` ведёт на quality-service, а не в каталог."""
    urls = service_urls()
    assert upstream_for("/api/v1/quality", urls) == urls["quality"]
    assert upstream_for("/api/v1/quality/ds_a", urls) == urls["quality"]
    assert upstream_for("/api/v1/quality/recalculate", urls) == urls["quality"]


def test_quality_upstream_uses_dedicated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """QR-2: адрес берётся из ``SERVICE_URL_QUALITY`` (compose) с фолбэком."""
    monkeypatch.setenv("SERVICE_URL_QUALITY", "http://quality-custom:9000")
    assert service_urls()["quality"] == "http://quality-custom:9000"
    monkeypatch.delenv("SERVICE_URL_QUALITY", raising=False)
    assert service_urls()["quality"].endswith(":8007")


async def test_gateway_forwards_rate_limit_and_retry_after_headers() -> None:
    """QR-6: ``Retry-After`` и ``X-RateLimit-*`` выживают за фасадом."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True},
            headers={
                "Retry-After": "7",
                "X-RateLimit-Limit": "5",
                "X-RateLimit-Remaining": "0",
            },
        )

    settings = Settings(app=AppSettings())
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = create_app(settings=settings, client=upstream, limiter=InMemoryRateLimiter())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/auth/login", json={})
    finally:
        await upstream.aclose()

    assert response.status_code == 200
    assert response.headers["Retry-After"] == "7"
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "0"


class _QualitySession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, _statement: Any, _params: Mapping[str, Any] | None = None) -> Any:
        return _QualityResult(self._rows)

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _QualityResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _QualityResult:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _QualityReport:
    async def latest_report(self, _dataset_id: str) -> Mapping[str, Any] | None:
        return {
            "quality_score": 0.42,
            "missing_rate": 0.11,
            "dup_rate": 0.0,
            "outlier_rate": 0.0,
            "anomalies_cnt": 3,
        }


async def test_gateway_proxies_quality_and_returns_camel_case() -> None:
    """QR-1/QR-2: фасад проксирует quality-service и отдаёт camelCase-контракт."""
    rows = [{"dataset_id": "ds_a", "name": "A", "quality_score": 0.9, "last_updated_at": None}]
    quality_app = create_quality_app(
        session_factory=cast(Any, lambda: _QualitySession(rows)),
        report_provider=_QualityReport(),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8007:
            transport = httpx.ASGITransport(app=quality_app)
            return await transport.handle_async_request(request)
        return httpx.Response(502, json={"error": {"code": "BAD_GATEWAY"}})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = create_app(
        settings=Settings(app=AppSettings()), client=upstream, limiter=InMemoryRateLimiter()
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/quality")
    finally:
        await upstream.aclose()

    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["datasetId"] == "ds_a"
    assert item["qualityScore"] == pytest.approx(0.42)
    assert item["missingRate"] == pytest.approx(0.11)
    assert item["anomaliesCnt"] == 3
    assert "dataset_id" not in item


async def test_gateway_requires_auth_for_quality_write() -> None:
    """M4: POST ``/quality/recalculate`` через фасад требует аутентификации."""
    gateway = create_app(settings=Settings(app=AppSettings()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/quality/recalculate", json={"datasets": {}})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_gateway_allows_public_quality_read() -> None:
    """QR-2: read-only Quality-page открыта через фасад без Bearer."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = create_app(
        settings=Settings(app=AppSettings()), client=upstream, limiter=InMemoryRateLimiter()
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/quality")
    finally:
        await upstream.aclose()

    assert response.status_code == 200
    assert response.json() == {"data": []}


def test_issue_demo_token_round_trip() -> None:
    """Токен демо-оператора валиден для секрета настроек."""
    token = issue_demo_token("us_operator", "unit-secret")
    assert token.startswith("usr_")
