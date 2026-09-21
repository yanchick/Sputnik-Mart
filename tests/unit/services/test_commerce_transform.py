"""Unit-тесты commerce → mart: разбор, дедуп, агрегация и загрузка (M1)."""

from __future__ import annotations

from typing import Any

import pytest

from contracts import CommerceTopic
from transform.commerce import (
    CommerceBatch,
    parse_commerce_event,
)
from transform.commerce_consumer import (
    EVENT_DEDUP_PREFIX,
    CommerceResult,
    CommerceTransformService,
    InMemoryEventDeduplicator,
    RedisEventDeduplicator,
    consume_commerce,
)
from transform.gold_readings import build_forecast_rows, load_forecasts
from transform.gold_sales import SALES_COLUMNS, build_sales_rows

pytestmark = pytest.mark.unit

AT = "2026-09-01T12:00:00+00:00"


def _order(event_id: str = "ev_o1", dataset: str = "ds_x", amount: float = 100.0) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "userId": "us_1",
        "at": AT,
        "orderId": f"or_{event_id}",
        "datasetId": dataset,
        "amount": amount,
    }


def _subscription(event_id: str = "ev_s1", dataset: str = "ds_x") -> dict[str, Any]:
    return {
        "eventId": event_id,
        "userId": "us_1",
        "at": AT,
        "subscriptionId": f"sub_{event_id}",
        "datasetId": dataset,
        "intervalSec": 60,
    }


def _download(event_id: str = "ev_d1", dataset: str = "ds_x") -> dict[str, Any]:
    return {
        "eventId": event_id,
        "userId": "us_1",
        "at": AT,
        "downloadId": f"dl_{event_id}",
        "datasetId": dataset,
        "format": "CSV",
    }


def _click(event_id: str = "ev_c1", dataset: str = "ds_x") -> dict[str, Any]:
    return {
        "eventId": event_id,
        "userId": "us_1",
        "at": AT,
        "datasetId": dataset,
        "source": "STORE",
    }


def _review(event_id: str = "ev_r1", dataset: str = "ds_x", rating: int = 5) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "userId": "us_1",
        "at": AT,
        "reviewId": f"rv_{event_id}",
        "datasetId": dataset,
        "rating": rating,
        "text": "good useful",
    }


class _FakeClickHouse:
    """Мини-клиент ClickHouse: запоминает команды и вставки."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.inserts: list[tuple[str, list[Any], list[str]]] = []

    async def command(self, query: str) -> None:
        self.commands.append(query)

    async def insert(
        self, table: str, data: list[Any], column_names: list[str] | None = None
    ) -> None:
        self.inserts.append((table, data, list(column_names or [])))


def test_parse_commerce_event_accepts_valid_and_rejects_invalid() -> None:
    event = parse_commerce_event(CommerceTopic.ORDERS.value, _order())
    assert event is not None
    assert event.event_id == "ev_o1"
    assert event.payload["datasetId"] == "ds_x"

    assert parse_commerce_event("commerce.unknown", _order()) is None
    assert parse_commerce_event(CommerceTopic.ORDERS.value, "not-a-mapping") is None
    assert parse_commerce_event(CommerceTopic.ORDERS.value, {"eventId": "ev_broken"}) is None


def test_sales_rows_count_orders_subscriptions_downloads_and_clicks() -> None:
    rows = build_sales_rows(
        [_order(), _order("ev_o2")],
        [_download()],
        subscriptions=[_subscription()],
        clicks=[_click(), _click("ev_c2")],
    )
    assert len(rows) == 1
    assert rows[0][2] == 3  # 2 заказа + 1 подписка
    assert rows[0][3] == 1  # downloads
    assert rows[0][4] == 2  # clicks
    assert rows[0][5] == pytest.approx(200.0)  # gross_amount


def test_sales_columns_include_clicks() -> None:
    assert "clicks" in SALES_COLUMNS


def test_commerce_batch_routes_events_to_marts() -> None:
    batch = CommerceBatch()
    for topic, payload in (
        (CommerceTopic.ORDERS.value, _order()),
        (CommerceTopic.SUBSCRIPTIONS.value, _subscription()),
        (CommerceTopic.DOWNLOADS.value, _download()),
        (CommerceTopic.CLICKS.value, _click()),
        (CommerceTopic.REVIEWS.value, _review()),
    ):
        event = parse_commerce_event(topic, payload)
        assert event is not None
        assert batch.add(event) is True

    assert batch.empty is False
    sales = batch.sales_rows()
    sentiment = batch.sentiment_rows()
    assert sales[0][2] == 2  # order + subscription
    assert sales[0][3] == 1
    assert sales[0][4] == 1
    assert sentiment[0][2] == 1
    assert sentiment[0][3] == pytest.approx(5.0)


async def test_dedup_skips_redelivery_and_flush_is_idempotent() -> None:
    client = _FakeClickHouse()
    service = CommerceTransformService(client, InMemoryEventDeduplicator())

    assert await service.process_message(CommerceTopic.ORDERS.value, _order()) == "accepted"
    assert await service.process_message(CommerceTopic.ORDERS.value, _order()) == "duplicate"
    assert await service.process_message(CommerceTopic.ORDERS.value, {"eventId": "x"}) == "invalid"

    flushed = await service.flush()
    assert flushed == {"mart_sales_daily": 1, "mart_sentiment_daily": 0}
    assert client.inserts[0][0] == "mart_sales_daily"
    assert client.inserts[0][1][0][2] == 1  # один заказ, дубль не учтён

    # Повторный flush переписывает ту же агрегацию (0 дублей: DELETE + INSERT).
    assert await service.flush() == {"mart_sales_daily": 1, "mart_sentiment_daily": 0}
    assert len(client.inserts) == 2
    assert client.inserts[1][1][0][2] == 1  # строка всё ещё одна


async def test_process_batch_aggregates_reviews() -> None:
    client = _FakeClickHouse()
    service = CommerceTransformService(client, InMemoryEventDeduplicator())
    result = await service.process_batch(
        CommerceTopic.REVIEWS.value, [_review(), _review("ev_r2", rating=1)]
    )
    assert result.accepted == 2
    flushed = await service.flush()
    assert flushed["mart_sentiment_daily"] == 1
    assert client.inserts[0][0] == "mart_sentiment_daily"


async def test_redis_deduplicator_uses_event_prefix() -> None:
    class _Store:
        def __init__(self) -> None:
            self.keys: list[str] = []

        async def reserve(self, key: str, _ttl: int) -> bool:
            if key in self.keys:
                return False
            self.keys.append(key)
            return True

    store = _Store()
    dedup = RedisEventDeduplicator(store)  # type: ignore[arg-type]
    assert await dedup.mark("ev_1") is True
    assert await dedup.mark("ev_1") is False
    assert store.keys == [f"{EVENT_DEDUP_PREFIX}ev_1"]


class _Message:
    def __init__(self, topic: str, value: Any) -> None:
        self.topic = topic
        self.value = value


class _FakeConsumer:
    """Итератор сообщений с коммитом оффсетов."""

    def __init__(self, messages: list[_Message]) -> None:
        self._messages = messages
        self.commits = 0

    def __aiter__(self) -> Any:
        async def _gen() -> Any:
            for message in self._messages:
                yield message

        return _gen()

    async def commit(self) -> None:
        self.commits += 1


async def test_consume_commerce_reads_commits_and_loads() -> None:
    client = _FakeClickHouse()
    service = CommerceTransformService(client, InMemoryEventDeduplicator())
    consumer = _FakeConsumer(
        [
            _Message(CommerceTopic.ORDERS.value, _order()),
            _Message(CommerceTopic.REVIEWS.value, _review()),
        ]
    )

    result = await consume_commerce(consumer, service, max_messages=2)

    assert result == CommerceResult(
        accepted=2, duplicates=0, invalid=0, loaded_sales=1, loaded_sentiment=1
    )
    assert consumer.commits == 2
    assert {insert[0] for insert in client.inserts} == {"mart_sales_daily", "mart_sentiment_daily"}


async def test_consume_commerce_flushes_periodically() -> None:
    client = _FakeClickHouse()
    service = CommerceTransformService(client, InMemoryEventDeduplicator())
    consumer = _FakeConsumer(
        [
            _Message(CommerceTopic.ORDERS.value, _order()),
            _Message(CommerceTopic.REVIEWS.value, _review()),
        ]
    )

    result = await consume_commerce(consumer, service, flush_every=1)

    assert result.accepted == 2
    assert result.loaded_sales == 1
    assert result.loaded_sentiment == 1
    assert len(client.inserts) >= 2


def test_build_and_load_forecasts() -> None:
    rows = build_forecast_rows(
        [
            {"station_id": "st_1", "metric": "TEMPERATURE", "hour": AT, "forecast_value": 12.5},
            {"station_id": "st_1", "metric": "TEMPERATURE", "hour": None, "forecast_value": 1.0},
            {"station_id": "", "metric": "TEMPERATURE", "hour": AT, "forecast_value": 1.0},
        ]
    )
    assert len(rows) == 1
    assert rows[0][3] == pytest.approx(12.5)

    class _Client:
        def __init__(self) -> None:
            self.commands: list[str] = []
            self.inserts: list[tuple[str, list[Any], list[str]]] = []

        async def command(self, query: str) -> None:
            self.commands.append(query)

        async def insert(
            self, table: str, data: list[Any], column_names: list[str] | None = None
        ) -> None:
            self.inserts.append((table, data, list(column_names or [])))

    import asyncio

    client = _Client()
    loaded = asyncio.run(load_forecasts(client, rows))
    assert loaded == 1
    assert client.inserts[0][0] == "forecasts"
    assert "DELETE" in client.commands[0]
    # Повторная загрузка снова делает DELETE + INSERT, но строк ровно одна.
    assert asyncio.run(load_forecasts(client, rows)) == 1
    assert len(client.inserts) == 2
