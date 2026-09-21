"""Тесты перечислений и обязательных полей контрактов (T027)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts import (
    ClickEventPayload,
    ClickSource,
    CreateOrderRequest,
    CreateSubscriptionRequest,
    DatasetCategory,
    DeadReadingPayload,
    DeadReadingReason,
    DownloadEventPayload,
    FileFormat,
    Metric,
    Order,
    OrderStatus,
    ReviewEventPayload,
    SchemaFieldType,
    SensorReadingPayload,
    Subscription,
    SubscriptionStatus,
)

pytestmark = pytest.mark.unit


def _enum_values(enum_cls: type) -> list[str]:
    return [member.value for member in enum_cls]  # type: ignore[attr-defined]


def test_order_status_exact() -> None:
    assert _enum_values(OrderStatus) == [
        "ORDER_PENDING",
        "ORDER_PAID",
        "ORDER_FULFILLED",
        "ORDER_CANCELLED",
    ]


def test_subscription_status_exact() -> None:
    assert _enum_values(SubscriptionStatus) == ["SUB_ACTIVE", "SUB_PAUSED", "SUB_CANCELLED"]


def test_dataset_category_exact() -> None:
    assert _enum_values(DatasetCategory) == [
        "WEATHER",
        "AIR_QUALITY",
        "ENERGY",
        "TRANSPORT",
        "COMMERCE",
    ]


def test_schema_field_type_exact() -> None:
    assert _enum_values(SchemaFieldType) == [
        "STRING",
        "INT",
        "DOUBLE",
        "BOOLEAN",
        "DATETIME",
        "GEO",
    ]


def test_metric_and_dead_reason_exact() -> None:
    assert _enum_values(Metric) == [
        "TEMPERATURE",
        "HUMIDITY",
        "PRESSURE",
        "PM2_5",
        "PM10",
        "NOISE",
        "ENERGY_KWH",
        "TRAFFIC_FLOW",
    ]
    assert _enum_values(DeadReadingReason) == [
        "NULL_VALUE",
        "OUT_OF_RANGE",
        "SCHEMA_MISMATCH",
        "DUPLICATE",
    ]


def test_file_format_and_click_source_exact() -> None:
    assert _enum_values(FileFormat) == ["CSV", "JSON", "PARQUET"]
    assert _enum_values(ClickSource) == ["STORE", "SAMPLE", "DOCS"]


def test_order_required_fields() -> None:
    with pytest.raises(ValidationError):
        Order.model_validate({"orderId": "od_1", "userId": "us_1"})

    order = Order.model_validate(
        {
            "orderId": "od_1",
            "userId": "us_1",
            "datasetId": "ds_x",
            "status": "ORDER_PAID",
            "createdAt": "2026-09-18T00:00:00Z",
        }
    )
    assert order.status is OrderStatus.ORDER_PAID
    assert order.amount is None


def test_subscription_required_fields() -> None:
    with pytest.raises(ValidationError):
        Subscription.model_validate({"subscriptionId": "sub_1", "userId": "us_1"})


def test_create_order_rejects_zero_quantity() -> None:
    with pytest.raises(ValidationError):
        CreateOrderRequest(datasetId="ds_x", quantity=0)


def test_create_subscription_interval_bounds() -> None:
    assert CreateSubscriptionRequest(datasetId="ds_x", intervalSec=60).intervalSec == 60
    with pytest.raises(ValidationError):
        CreateSubscriptionRequest(datasetId="ds_x", intervalSec=59)
    with pytest.raises(ValidationError):
        CreateSubscriptionRequest(datasetId="ds_x", intervalSec=86401)


def test_sensor_reading_received_at_required() -> None:
    payload = {
        "readingId": "rd_1",
        "stationId": "st_1",
        "providerId": "pv_1",
        "metric": "TEMPERATURE",
        "value": 18.4,
        "unit": "C",
        "measuredAt": "2026-09-18T00:00:00Z",
    }
    with pytest.raises(ValidationError):
        SensorReadingPayload.model_validate(payload)

    reading = SensorReadingPayload.model_validate({**payload, "receivedAt": "2026-09-18T00:00:01Z"})
    assert reading.metric is Metric.TEMPERATURE


def test_dead_reading_reason_and_raw() -> None:
    dead = DeadReadingPayload.model_validate(
        {"readingId": "rd_bad", "reason": "OUT_OF_RANGE", "raw": {"value": -900}}
    )
    assert dead.reason is DeadReadingReason.OUT_OF_RANGE


def test_review_event_rating_bounds() -> None:
    base = {"eventId": "ev_1", "userId": "us_1", "at": "2026-09-18T00:00:00Z"}
    with pytest.raises(ValidationError):
        ReviewEventPayload.model_validate(
            {**base, "reviewId": "rv_1", "datasetId": "ds_1", "rating": 6, "text": "x"}
        )
    with pytest.raises(ValidationError):
        ReviewEventPayload.model_validate(
            {**base, "reviewId": "rv_1", "datasetId": "ds_1", "rating": 0, "text": "x"}
        )


def test_click_and_download_events() -> None:
    base = {"eventId": "ev_1", "userId": "us_1", "at": "2026-09-18T00:00:00Z"}
    click = ClickEventPayload.model_validate({**base, "datasetId": "ds_1", "source": "SAMPLE"})
    assert click.source is ClickSource.SAMPLE

    download = DownloadEventPayload.model_validate(
        {**base, "downloadId": "dl_1", "datasetId": "ds_1", "format": "PARQUET"}
    )
    assert download.format is FileFormat.PARQUET
