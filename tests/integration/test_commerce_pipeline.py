"""Интеграционный тест commerce.* → mart_* на Redpanda + ClickHouse (M1).

Тест поднимает реальные Redpanda и ClickHouse, публикует события пяти
commerce-топиков, прогоняет консьюмер и проверяет, что ``mart_sales_daily`` и
``mart_sentiment_daily`` наполнились. Повторная доставка тех же событий
(новый consumer-group) не увеличивает счётчики (at-least-once + дедуп).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from contracts import CommerceTopic
from db.kafka import create_consumer, create_producer, produce_json
from transform.commerce import COMMERCE_TOPICS
from transform.commerce_consumer import (
    CommerceResult,
    CommerceTransformService,
    EventDeduplicator,
    InMemoryEventDeduplicator,
    consume_commerce,
)

pytestmark = pytest.mark.integration

AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC).isoformat()
DATASET = "ds_commerce-it"


def _events() -> list[tuple[str, dict[str, Any], str]]:
    """По одному событию каждого топика (плюс второй заказ) с фиксированными id."""
    return [
        (
            CommerceTopic.ORDERS.value,
            {
                "eventId": "ev_o1",
                "userId": "us_1",
                "at": AT,
                "orderId": "or_1",
                "datasetId": DATASET,
                "amount": 100.0,
            },
            "or_1",
        ),
        (
            CommerceTopic.ORDERS.value,
            {
                "eventId": "ev_o2",
                "userId": "us_1",
                "at": AT,
                "orderId": "or_2",
                "datasetId": DATASET,
                "amount": 50.0,
            },
            "or_2",
        ),
        (
            CommerceTopic.SUBSCRIPTIONS.value,
            {
                "eventId": "ev_s1",
                "userId": "us_1",
                "at": AT,
                "subscriptionId": "sub_1",
                "datasetId": DATASET,
                "intervalSec": 60,
            },
            "sub_1",
        ),
        (
            CommerceTopic.DOWNLOADS.value,
            {
                "eventId": "ev_d1",
                "userId": "us_1",
                "at": AT,
                "downloadId": "dl_1",
                "datasetId": DATASET,
                "format": "CSV",
            },
            "dl_1",
        ),
        (
            CommerceTopic.CLICKS.value,
            {
                "eventId": "ev_c1",
                "userId": "us_1",
                "at": AT,
                "datasetId": DATASET,
                "source": "STORE",
            },
            DATASET,
        ),
        (
            CommerceTopic.REVIEWS.value,
            {
                "eventId": "ev_r1",
                "userId": "us_1",
                "at": AT,
                "reviewId": "rv_1",
                "datasetId": DATASET,
                "rating": 5,
                "text": "good useful",
            },
            "rv_1",
        ),
    ]


async def _produce(bootstrap: str, events: list[tuple[str, dict[str, Any], str]]) -> None:
    producer = create_producer(bootstrap)
    await producer.start()
    try:
        for topic, payload, key in events:
            await produce_json(producer, topic, payload, key=key)
    finally:
        await producer.stop()


async def _consume(
    bootstrap: str,
    clickhouse: Any,
    dedup: EventDeduplicator,
    group: str,
    count: int,
) -> CommerceResult:
    consumer = create_consumer(list(COMMERCE_TOPICS), group, bootstrap)
    await consumer.start()
    try:
        service = CommerceTransformService(clickhouse, dedup)
        return await consume_commerce(consumer, service, max_messages=count)
    finally:
        await consumer.stop()


async def _count(clickhouse: Any, table: str) -> int:
    result = await clickhouse.execute(
        f"SELECT count() FROM {table} WHERE dataset_id = {{dataset:String}}",
        {"dataset": DATASET},
    )
    return int(result.result_rows[0][0])


def test_commerce_events_populate_marts_and_redelivery_is_idempotent(
    clickhouse_client: Any, docker_available: bool
) -> None:
    from testcontainers.community.kafka import RedpandaContainer

    events = _events()
    with RedpandaContainer("redpandadata/redpanda:v24.1.7") as redpanda:
        bootstrap = redpanda.get_bootstrap_server()
        asyncio.run(_produce(bootstrap, events))

        dedup = InMemoryEventDeduplicator()
        first = asyncio.run(_consume(bootstrap, clickhouse_client, dedup, "commerce-it-a", 6))
        assert first.accepted == 6
        assert first.loaded_sales == 1
        assert first.loaded_sentiment == 1
        assert asyncio.run(_count(clickhouse_client, "mart_sales_daily")) == 1
        assert asyncio.run(_count(clickhouse_client, "mart_sentiment_daily")) == 1

        # Повторная доставка в новый consumer-group: все события — дубли.
        second = asyncio.run(_consume(bootstrap, clickhouse_client, dedup, "commerce-it-b", 6))
        assert second.accepted == 0
        assert second.duplicates == 6
        assert second.loaded == 0
        assert asyncio.run(_count(clickhouse_client, "mart_sales_daily")) == 1
        assert asyncio.run(_count(clickhouse_client, "mart_sentiment_daily")) == 1
