"""Интеграционный тест идемпотентности заказа UNIQUE(user_id, key) (T068)."""

from __future__ import annotations

import asyncio

import pytest

from support import DEMO_DATASET, Apps, auth_header, client_for, token_for

pytestmark = pytest.mark.integration


async def test_repeated_order_returns_same_id(apps: Apps) -> None:
    """Повтор с тем же ключом не создаёт новый заказ (FR-006, SC-005)."""
    async with client_for(apps.order) as client:
        token = await token_for(apps)
        headers = {**auth_header(token), "Idempotency-Key": "idem-integration-1"}
        body = {"datasetId": DEMO_DATASET}

        first = await client.post("/api/v1/orders", json=body, headers=headers)
        second = await client.post("/api/v1/orders", json=body, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["orderId"] == second.json()["orderId"]

        listing = await client.get("/api/v1/orders", headers=auth_header(token))
        matching = [item for item in listing.json()["data"] if item["datasetId"] == DEMO_DATASET]
        assert len({item["orderId"] for item in matching}) == len(matching)


async def test_concurrent_orders_do_not_duplicate(apps: Apps) -> None:
    """Параллельные запросы с одним ключом сходятся к одному заказу (SC-005)."""
    async with client_for(apps.order) as client:
        token = await token_for(apps)
        headers = {**auth_header(token), "Idempotency-Key": "idem-integration-concurrent"}
        body = {"datasetId": "ds_air-quality"}

        responses = await asyncio.gather(
            client.post("/api/v1/orders", json=body, headers=headers),
            client.post("/api/v1/orders", json=body, headers=headers),
        )

        assert all(response.status_code == 201 for response in responses)
        order_ids = {response.json()["orderId"] for response in responses}
        assert len(order_ids) == 1
