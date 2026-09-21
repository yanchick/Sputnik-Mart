"""Unit-тесты delivery: право скачивания и форматы выгрузки (T064)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from delivery.access import (
    PAID_STATUSES,
    get_subscription,
    has_download_access,
    user_id_for_api_key,
)
from delivery.downloads import (
    NullDownloadPublisher,
    build_download_event,
    publish_download,
    record_download,
)
from delivery.service import build_rows, load_fields, render_content

from contracts import FileFormat
from observability import ApiError

pytestmark = pytest.mark.unit


class _StubClient:
    """HTTP-клиент-заглушка для проверки доступа через владельца (M6)."""

    def __init__(self, payload: Any = None) -> None:
        self.payload = payload if payload is not None else {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get_json(self, path: str, *, params: Any = None, headers: Any = None) -> Any:
        self.calls.append((path, "GET", dict(params or {})))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def post_json(self, path: str, *, json: Any = None, headers: Any = None) -> Any:
        self.calls.append((path, "POST", dict(json or {})))
        return self.payload


class _ExecuteSession:
    """Мини-сессия, записывающая SQL-вызовы без БД."""

    def __init__(self) -> None:
        self.executed: list[tuple[Any, ...]] = []

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        """Запомнить вызов execute."""
        self.executed.append((*args, kwargs))


def test_paid_statuses_define_download_access() -> None:
    assert PAID_STATUSES == ("ORDER_PAID", "ORDER_FULFILLED")


def test_render_content_all_formats() -> None:
    fields: list[dict[str, Any]] = [
        {"name": "temperature", "type": "DOUBLE", "unit": "C", "nullable": False, "ordinal": 0},
        {"name": "station", "type": "STRING", "unit": None, "nullable": True, "ordinal": 1},
    ]

    csv_content, csv_media, csv_ext = render_content("ds_test", fields, FileFormat.CSV)
    assert csv_media == "text/csv"
    assert csv_ext == "csv"
    assert b"readingId" in csv_content

    json_content, json_media, _ = render_content("ds_test", fields, FileFormat.JSON)
    assert json_media == "application/json"
    assert isinstance(json.loads(json_content), list)

    parquet_content, parquet_media, parquet_ext = render_content(
        "ds_test", fields, FileFormat.PARQUET
    )
    assert parquet_media == "application/octet-stream"
    assert parquet_ext == "parquet"
    assert parquet_content[:4] == b"PAR1"


def test_download_rows_are_deterministic() -> None:
    fields = [{"name": "value", "type": "INT", "unit": None, "nullable": False, "ordinal": 0}]

    assert build_rows("ds_test", fields) == build_rows("ds_test", fields)


async def test_record_download_and_event() -> None:
    session = _ExecuteSession()

    record = await record_download(
        session,  # type: ignore[arg-type]
        user_id="us_1",
        dataset_id="ds_test",
        fmt=FileFormat.CSV,
        size=10,
    )

    assert record.download_id.startswith("dl_")
    assert len(session.executed) == 1
    event = build_download_event(record)
    assert event["format"] == "CSV"
    assert event["datasetId"] == "ds_test"

    publisher = NullDownloadPublisher()
    await publish_download(publisher, record)
    assert publisher.published[0][0] == "commerce.downloads"


async def test_download_access_delegates_to_order() -> None:
    """M6: delivery проверяет оплату через order-сервис, не читая orders.orders."""
    order = _StubClient({"datasetId": "ds_test", "hasAccess": True})

    assert await has_download_access(order, "us_1", "ds_test")
    path, _method, params = order.calls[0]
    assert path == "/api/v1/orders/access"
    assert params == {"datasetId": "ds_test"}


async def test_api_key_resolution_delegates_to_identity() -> None:
    """M6: delivery разрешает машинный ключ через identity-сервис."""
    identity = _StubClient({"userId": "us_machine"})

    resolved = await user_id_for_api_key(identity, "sk_demo")

    assert resolved == "us_machine"
    assert identity.calls[0][0] == "/api/v1/api-keys/resolve"


async def test_get_subscription_maps_contract_to_snake_case() -> None:
    order = _StubClient(
        {
            "subscriptionId": "sub_1",
            "userId": "us_1",
            "datasetId": "ds_test",
            "status": "SUB_ACTIVE",
        }
    )

    subscription = await get_subscription(order, "sub_1", "us_1")

    assert subscription == {
        "subscription_id": "sub_1",
        "user_id": "us_1",
        "dataset_id": "ds_test",
        "status": "SUB_ACTIVE",
    }


async def test_get_subscription_returns_none_on_not_found() -> None:
    order = _StubClient(ApiError(404, "NOT_FOUND", "Подписка не найдена"))

    assert await get_subscription(order, "sub_x", "us_1") is None


async def test_load_fields_reads_catalog_schema() -> None:
    """M6: схема датасета приходит из catalog-сервиса."""
    catalog = _StubClient(
        [{"name": "temperature", "type": "DOUBLE", "unit": "C", "nullable": False, "ordinal": 0}]
    )

    fields = await load_fields(catalog, "ds_test", "us_1")

    assert fields[0]["name"] == "temperature"
    assert catalog.calls[0][0] == "/api/v1/datasets/ds_test/schema"
