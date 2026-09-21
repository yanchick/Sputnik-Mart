"""Unit-тесты catalog: конверсия карточки, схема и образцы (T062, M6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from catalog.main import create_app
from catalog.repository import Dataset, DatasetField
from catalog.sample import SAMPLE_ROWS, build_rows, render_sample
from catalog.service import to_contract, to_schema_field

from config import AppSettings, Settings
from contracts import DatasetCategory, FileFormat
from observability import build_pagination, encode_token

pytestmark = pytest.mark.unit


class _CatalogSession:
    """Мини-сессия, фиксирующая SQL-обновления без БД."""

    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []
        self.commits = 0

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> None:
        self.executed.append(dict(params or {}))

    async def commit(self) -> None:
        self.commits += 1

    async def close(self) -> None:
        return None


class _CatalogSessionFactory:
    def __init__(self) -> None:
        self.session = _CatalogSession()

    def __call__(self) -> _CatalogSession:
        return self.session


class _StubIdentity:
    """Заглушка identity для проверки ключей в каталоге (M6)."""

    def __init__(self, user_id: str | None) -> None:
        self._user_id = user_id

    async def get_json(self, path: str, **kwargs: object) -> dict[str, object]:
        return {}

    async def post_json(self, path: str, **kwargs: object) -> dict[str, object]:
        return {"userId": self._user_id}


def _dataset() -> Dataset:
    return Dataset(
        dataset_id="ds_test",
        provider_id="pv_test",
        name="Тестовый",
        category=DatasetCategory.WEATHER.value,
        frequency_sec=60,
        volume_estimate="1M rows",
        price_per_unit=Decimal("1200.00"),
        quality_score=Decimal("0.920"),
        licence="sputnik_edu_v1",
        last_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _fields() -> list[DatasetField]:
    return [
        DatasetField(
            dataset_id="ds_test",
            name="temperature",
            ordinal=0,
            type="DOUBLE",
            unit="C",
            nullable=False,
        ),
        DatasetField(
            dataset_id="ds_test", name="station", ordinal=1, type="STRING", unit=None, nullable=True
        ),
    ]


def test_to_contract_maps_all_fields() -> None:
    card = to_contract(_dataset())

    assert card.datasetId == "ds_test"
    assert card.category is DatasetCategory.WEATHER
    assert card.pricePerUnit == 1200.0
    assert card.qualityScore == 0.92


def test_to_schema_field_preserves_ordinal() -> None:
    field = to_schema_field(_fields()[1])

    assert field.name == "station"
    assert field.nullable is True
    assert field.ordinal == 1


def test_sample_is_deterministic_and_bounded() -> None:
    dataset = _dataset()
    fields = _fields()

    first = build_rows(dataset, fields)
    second = build_rows(dataset, fields)

    assert first == second
    assert len(first) == SAMPLE_ROWS
    assert "readingId" in first[0]


def test_render_sample_formats() -> None:
    dataset = _dataset()
    fields = _fields()

    csv_content, csv_media = render_sample(dataset, fields, FileFormat.CSV)
    assert csv_media == "text/csv"
    assert b"readingId" in csv_content

    json_content, json_media = render_sample(dataset, fields, FileFormat.JSON)
    assert json_media == "application/json"
    assert isinstance(json.loads(json_content), list)

    parquet_content, parquet_media = render_sample(dataset, fields, FileFormat.PARQUET)
    assert parquet_media == "application/octet-stream"
    assert parquet_content[:4] == b"PAR1"


def test_pagination_has_more_flag() -> None:
    first = build_pagination(page=1, page_size=20, total=45)
    last = build_pagination(page=3, page_size=20, total=45)

    assert first["totalPages"] == 3
    assert first["hasMore"] is True
    assert last["hasMore"] is False


async def test_quality_scores_endpoint_rejects_unauthenticated() -> None:
    """M6: внутренняя запись qualityScore требует оператора (401)."""
    app = create_app(
        session_factory=cast(Any, _CatalogSessionFactory()),
        identity_client=cast(Any, _StubIdentity(None)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/datasets/quality-scores", json={"scores": {"ds_a": 0.5}}
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_quality_scores_endpoint_updates_catalog() -> None:
    """M6: оператор обновляет qualityScore через эндпоинт-владелец."""
    secret = "unit-secret"
    factory = _CatalogSessionFactory()
    app = create_app(
        settings=Settings(app=AppSettings(auth_secret=secret)),
        session_factory=cast(Any, factory),
        identity_client=cast(Any, _StubIdentity("us_operator")),
    )
    token = encode_token("us_operator", secret)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/datasets/quality-scores",
            json={"scores": {"ds_a": 0.5, "ds_b": 0.8}},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"updated": ["ds_a", "ds_b"], "count": 2}
    assert factory.session.commits == 1
    assert [call["dataset_id"] for call in factory.session.executed] == ["ds_a", "ds_b"]
    assert factory.session.executed[0]["score"] == pytest.approx(0.5)
