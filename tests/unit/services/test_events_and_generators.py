"""Unit-тесты событийных билдеров, идемпотентности слоёв и генераторов.

Покрывают публикацию commerce-событий, дедупликацию silver и CLI ``sim`` —
ветки, которые не проверяются контрактными/e2e сценариями.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from order.repository import Order, Subscription
from review.repository import Review

from catalog import clicks
from contracts import ClickSource
from order import events as order_events
from review import events as review_events
from sensor_gateway import publisher as sensor_publisher
from sim import cli as sim_cli
from sim.buyers import build_behavior, build_buyers, write_behavior
from sim.providers import write_partner_csvs
from validation.idempotency import dedupe_by_key, merge_frames, row_fingerprint, silver_key

pytestmark = pytest.mark.unit


class _FakeProducer:
    def __init__(self) -> None:
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


def _order() -> Order:
    return Order(
        order_id="ord_1",
        user_id="us_1",
        dataset_id="ds_x",
        amount=100,
        idempotency_key="key-1",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _subscription() -> Subscription:
    return Subscription(
        subscription_id="sub_1",
        user_id="us_1",
        dataset_id="ds_x",
        interval_sec=300,
        started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _review() -> Review:
    return Review(
        review_id="rv_1",
        user_id="us_1",
        dataset_id="ds_x",
        rating=5,
        text="ok",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


async def test_order_events_publish() -> None:
    publisher = order_events.NullPublisher()

    assert order_events.build_order_event(_order(), "us_1")["orderId"] == "ord_1"
    await order_events.publish_order(publisher, _order(), "us_1")
    await order_events.publish_subscription(publisher, _subscription(), "us_1")

    topics = [item[0] for item in publisher.published]
    assert topics == ["commerce.orders", "commerce.subscriptions"]


async def test_order_kafka_publisher_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = _FakeProducer()
    published: list[tuple[str, dict[str, Any], str]] = []

    monkeypatch.setattr(order_events, "create_producer", lambda _: producer)

    async def _produce(*args: Any, **kwargs: Any) -> None:
        published.append((args[1], dict(args[2]), kwargs.get("key", "")))

    monkeypatch.setattr(order_events, "produce_json", _produce)

    kafka = order_events.KafkaEventPublisher("localhost:9092")
    await kafka.publish("commerce.orders", {"a": 1}, "ord_1")
    assert producer.started is True
    assert published[0][0] == "commerce.orders"
    await kafka.stop()
    assert producer.started is False


async def test_review_and_click_events_publish() -> None:
    review_publisher = review_events.NullReviewPublisher()
    await review_events.publish_review(review_publisher, _review())
    assert review_events.build_review_event(_review())["reviewId"] == "rv_1"
    assert review_publisher.published[0][0] == "commerce.reviews"

    click_publisher = clicks.NullClickPublisher()
    await clicks.publish_click(click_publisher, "ds_x", "us_1", ClickSource.STORE)
    event = clicks.build_click_event("ds_x", "us_1", ClickSource.SAMPLE)
    assert event["datasetId"] == "ds_x"
    assert event["source"] == "SAMPLE"
    assert click_publisher.published[0][0] == "commerce.clicks"


async def test_sensor_publishers_and_topics() -> None:
    publisher = sensor_publisher.NullPublisher()
    await publisher.publish({"readingId": "rd_1"}, "st_1")
    assert publisher.published[0][0] == "st_1"
    assert sensor_publisher.readings_topic() == "sensors.readings.v1"
    assert sensor_publisher.dlq_topic() == "sensors.readings.dlq"

    kafka = sensor_publisher.KafkaPublisher("localhost:9092", "sensors.readings.v1")
    assert kafka._topic == "sensors.readings.v1"


def test_idempotent_layer_helpers() -> None:
    frame = pd.DataFrame({"reading_id": ["a", "a", "b"], "value": [1, 2, 3]})
    deduped = dedupe_by_key(frame)
    assert list(deduped["reading_id"]) == ["a", "b"]
    assert list(deduped["value"]) == [2, 3]
    assert merge_frames(frame.iloc[0:0], frame).shape[0] == 2
    assert merge_frames(frame, frame.iloc[0:0]).shape[0] == 2
    assert row_fingerprint({"b": 2, "a": 1}) == "1|2"
    assert dedupe_by_key(frame.iloc[0:0]).empty
    assert silver_key("ds_x", datetime(2026, 9, 1, tzinfo=UTC).date()) == "silver/ds_x/2026-09-01"


def test_generators_write_deterministic_artifacts(tmp_path: Path) -> None:
    first = write_partner_csvs(tmp_path / "first", seed=42)
    second = write_partner_csvs(tmp_path / "second", seed=42)

    assert len(first) == len(second) > 0
    assert first[0].read_bytes() == second[0].read_bytes()

    behavior_path = write_behavior(tmp_path, seed=42)
    assert behavior_path.is_file()
    assert build_behavior(seed=42) == build_behavior(seed=42)
    assert len(build_buyers(seed=42, count=5)) == 5


def test_sim_cli_sensors_and_dirty(tmp_path: Path) -> None:
    sensors_out = tmp_path / "sensors.ndjson"
    assert (
        sim_cli.main(
            [
                "sensors",
                "--seed",
                "1",
                "--stations",
                "2",
                "--volume",
                "4",
                "--out",
                str(sensors_out),
            ]
        )
        == 0
    )
    assert sensors_out.read_text(encoding="utf-8")

    dirty_out = tmp_path / "dirty.ndjson"
    assert (
        sim_cli.main(
            [
                "dirty",
                "--input",
                str(sensors_out),
                "--seed",
                "1",
                "--missing",
                "0.5",
                "--duplicate",
                "0.5",
                "--out",
                str(dirty_out),
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in dirty_out.read_text(encoding="utf-8").splitlines()]
    assert records
