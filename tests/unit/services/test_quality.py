"""Unit-тесты quality-service: пересчёт ``qualityScore`` в ``[0..1]`` (T106)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from config import AppSettings, Settings
from contracts import quality_score_from_rates
from observability import encode_token, set_data_freshness
from quality import service
from quality.main import create_app

pytestmark = pytest.mark.unit


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rows = rows or []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append(dict(params or {}))
        return _FakeResult(self._rows)


class _FakeCatalog:
    """Каталог-заглушка: фиксирует вызовы внутреннего обновления (M6)."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return {}

    async def post_json(
        self,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.posts.append({"path": path, "json": json, "headers": headers})
        scores = dict(json.get("scores", {})) if isinstance(json, dict) else {}
        return {"updated": list(scores), "count": len(scores)}


class _StubIdentity:
    """Identity-заглушка, разрешающая любой ключ в заданного пользователя."""

    def __init__(self, user_id: str | None) -> None:
        self._user_id = user_id

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return {}

    async def post_json(
        self,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return {"userId": self._user_id}


def test_quality_score_is_clamped_and_matches_shared_formula() -> None:
    expected = quality_score_from_rates(
        missing_rate=0.2, dup_rate=0.1, outlier_rate=0.05, gap_rate=0.0
    )
    report = {
        "missing_rate": 0.2,
        "dup_rate": 0.1,
        "outlier_rate": 0.05,
        "gap_rate": 0.0,
    }
    assert service.quality_score_from_report(report) == pytest.approx(expected)
    assert service.quality_score_from_report({"quality_score": 5.0}) == 1.0
    assert service.quality_score_from_report({"quality_score": -1.0}) == 0.0


async def test_recalculate_delegates_to_catalog_owner() -> None:
    """M6: quality пишет qualityScore через catalog-API, а не в чужую таблицу."""
    catalog = _FakeCatalog()
    updated = await service.recalculate_quality_scores(
        {
            "ds_a": {"quality_score": 0.5},
            "ds_b": {"quality_score": 0.8},
        },
        catalog,  # type: ignore[arg-type]
    )
    assert updated == ["ds_a", "ds_b"]
    post = catalog.posts[0]
    assert post["path"] == "/api/v1/datasets/quality-scores"
    assert post["json"]["scores"]["ds_a"] == pytest.approx(0.5)
    assert post["json"]["scores"]["ds_b"] == pytest.approx(0.8)


async def test_recalculate_empty_reports_is_noop() -> None:
    catalog = _FakeCatalog()
    assert await service.recalculate_quality_scores({}, catalog) == []  # type: ignore[arg-type]
    assert catalog.posts == []


async def test_list_and_get_snapshots() -> None:
    rows = [
        {
            "dataset_id": "ds_a",
            "name": "A",
            "quality_score": 0.75,
            "last_updated_at": None,
        }
    ]
    session = cast(AsyncSession, _FakeSession(rows))
    snapshots = await service.list_quality_snapshots(session)
    assert snapshots[0].dataset_id == "ds_a"
    assert snapshots[0].quality_score == pytest.approx(0.75)
    merged = service.merge_report(
        snapshots[0],
        {"quality_score": 0.4, "missing_rate": 0.1, "dup_rate": 0.0, "outlier_rate": 0.0},
    )
    assert merged.missing_rate == pytest.approx(0.1)
    assert merged.quality_score == pytest.approx(0.4)


class _HttpSession:
    """Мини-сессия для HTTP-тестов quality-service (без реальной БД)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.commits = 0

    async def execute(self, _statement: Any, _params: dict[str, Any] | None = None) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self.commits += 1

    async def close(self) -> None:
        return None


class _HttpSessionFactory:
    """Фабрика, совместимая с ``request.app.state.session_factory``."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.session = _HttpSession(rows)

    def __call__(self) -> _HttpSession:
        return self.session


class _ReportProvider:
    """Провайдер отчёта с фиксированным ответом."""

    def __init__(self, report: Mapping[str, Any] | None) -> None:
        self._report = report

    async def latest_report(self, _dataset_id: str) -> Mapping[str, Any] | None:
        return self._report


async def test_quality_payload_is_camel_case_and_merges_report() -> None:
    """QR-1: оба endpoint'а отдают camelCase и реальные показатели отчёта."""
    rows = [{"dataset_id": "ds_a", "name": "A", "quality_score": 0.75, "last_updated_at": None}]
    app = create_app(
        session_factory=cast(Any, _HttpSessionFactory(rows)),
        report_provider=_ReportProvider(
            {
                "quality_score": 0.4,
                "missing_rate": 0.1,
                "dup_rate": 0.2,
                "outlier_rate": 0.3,
                "anomalies_cnt": 7,
            }
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listing = await client.get("/api/v1/quality")
        detail = await client.get("/api/v1/quality/ds_a")

    assert listing.status_code == 200
    item = listing.json()["data"][0]
    assert set(item) == {
        "datasetId",
        "name",
        "qualityScore",
        "missingRate",
        "dupRate",
        "outlierRate",
        "anomaliesCnt",
        "dt",
    }
    assert item["qualityScore"] == pytest.approx(0.4)
    assert item["missingRate"] == pytest.approx(0.1)
    assert item["dupRate"] == pytest.approx(0.2)
    assert item["outlierRate"] == pytest.approx(0.3)
    assert item["anomaliesCnt"] == 7
    assert detail.json() == item


async def test_metrics_endpoint_refreshes_lag_and_freshness() -> None:
    """M3: ``/metrics`` публикует лаг/свежесть из рантайм-источника."""
    calls: list[str] = []

    async def refresher(_session: Any) -> None:
        calls.append("refresh")
        set_data_freshness("ds_metrics_endpoint", 12.0)

    app = create_app(
        session_factory=cast(Any, _HttpSessionFactory([])),
        metrics_refresher=refresher,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "sputnik_data_freshness_seconds" in response.text
    assert calls == ["refresh"]


async def test_metrics_endpoint_survives_refresh_failure() -> None:
    """Ошибка обновления метрик не должна ломать скрейп Prometheus."""

    async def broken_refresher(_session: Any) -> None:
        raise RuntimeError("clickhouse down")

    app = create_app(
        session_factory=cast(Any, _HttpSessionFactory([])),
        metrics_refresher=broken_refresher,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200


async def test_recalculate_rejects_unauthenticated() -> None:
    """M4: write-эндпоинт без Bearer/``X-Api-Key`` — 401 в едином конверте."""
    app = create_app(session_factory=cast(Any, _HttpSessionFactory([])))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/quality/recalculate", json={"datasets": {}})

    assert response.status_code == 401
    payload = response.json()["error"]
    assert payload["code"] == "UNAUTHORIZED"
    assert "requestId" in payload


async def test_recalculate_rejects_invalid_bearer() -> None:
    """M4: подпись токена проверяется — подделка отклоняется 401."""
    app = create_app(session_factory=cast(Any, _HttpSessionFactory([])))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/quality/recalculate",
            json={"datasets": {}},
            headers={"Authorization": "Bearer us_forged.deadbeef"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_recalculate_allows_bearer_or_api_key() -> None:
    """M4: валидный Bearer или известный машинный ключ проходят авторизацию."""
    secret = "unit-secret"
    factory = _HttpSessionFactory([{"user_id": "us_operator"}])
    app = create_app(
        settings=Settings(app=AppSettings(auth_secret=secret)),
        session_factory=cast(Any, factory),
        identity_client=cast(Any, _StubIdentity("us_operator")),
    )
    token = encode_token("us_operator", secret)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        bearer = await client.post(
            "/api/v1/quality/recalculate",
            json={"datasets": {}},
            headers={"Authorization": f"Bearer {token}"},
        )
        api_key = await client.post(
            "/api/v1/quality/recalculate",
            json={"datasets": {}},
            headers={"X-Api-Key": "sk_operator"},
        )

    assert bearer.status_code == 200
    assert bearer.json() == {"updated": [], "count": 0}
    assert api_key.status_code == 200
    assert api_key.json() == {"updated": [], "count": 0}


async def test_recalculate_forwards_operator_auth_to_catalog() -> None:
    """M6: запись qualityScore идёт в каталог с проброшенной авторизацией."""
    catalog = _FakeCatalog()
    secret = "unit-secret"
    app = create_app(
        settings=Settings(app=AppSettings(auth_secret=secret)),
        session_factory=cast(Any, _HttpSessionFactory([])),
        catalog_client=cast(Any, catalog),
        identity_client=cast(Any, _StubIdentity("us_operator")),
    )
    token = encode_token("us_operator", secret)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/quality/recalculate",
            json={"datasets": {"ds_a": {"quality_score": 0.7}}},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert catalog.posts[0]["path"] == "/api/v1/datasets/quality-scores"
    assert catalog.posts[0]["headers"]["Authorization"] == f"Bearer {token}"
    assert response.json()["updated"] == ["ds_a"]


async def test_recalculate_rejects_unknown_api_key() -> None:
    """M6: неизвестный ключ (identity вернул null) отклоняется 401."""
    app = create_app(
        session_factory=cast(Any, _HttpSessionFactory([])),
        identity_client=cast(Any, _StubIdentity(None)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/quality/recalculate",
            json={"datasets": {}},
            headers={"X-Api-Key": "sk_unknown"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
