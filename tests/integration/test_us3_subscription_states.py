"""Интеграционный тест статусов ``SUB_PAUSED``/``SUB_CANCELLED`` (T138, FR-009)."""

from __future__ import annotations

import pytest

from support import DEMO_DATASET, Apps, auth_header, client_for, token_for

pytestmark = pytest.mark.integration


async def _subscribe(apps: Apps, token: str) -> str:
    async with client_for(apps.order) as order_client:
        response = await order_client.post(
            "/api/v1/subscriptions",
            json={"datasetId": DEMO_DATASET, "intervalSec": 300},
            headers=auth_header(token),
        )
    assert response.status_code == 201, response.text
    return str(response.json()["subscriptionId"])


async def _change(apps: Apps, token: str, subscription_id: str, action: str) -> dict[str, object]:
    async with client_for(apps.order) as order_client:
        response = await order_client.post(
            f"/api/v1/subscriptions/{subscription_id}/{action}", headers=auth_header(token)
        )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _stream_status(apps: Apps, token: str, subscription_id: str) -> int:
    async with client_for(apps.delivery) as client:
        response = await client.get(
            f"/api/v1/streams/{subscription_id}", headers=auth_header(token)
        )
    return response.status_code


async def test_pause_resume_cancel_semantics(apps: Apps) -> None:
    token = await token_for(apps)
    subscription_id = await _subscribe(apps, token)
    assert await _stream_status(apps, token, subscription_id) == 200

    paused = await _change(apps, token, subscription_id, "pause")
    assert paused["status"] == "SUB_PAUSED"
    assert await _stream_status(apps, token, subscription_id) == 403

    resumed = await _change(apps, token, subscription_id, "resume")
    assert resumed["status"] == "SUB_ACTIVE"
    assert await _stream_status(apps, token, subscription_id) == 200

    cancelled = await _change(apps, token, subscription_id, "cancel")
    assert cancelled["status"] == "SUB_CANCELLED"
    assert await _stream_status(apps, token, subscription_id) == 403


async def test_cancelled_is_terminal_and_purchased_data_stays_available(apps: Apps) -> None:
    token = await token_for(apps)
    subscription_id = await _subscribe(apps, token)

    async with client_for(apps.order) as order_client:
        order = await order_client.post(
            "/api/v1/orders",
            json={"datasetId": DEMO_DATASET},
            headers={**auth_header(token), "Idempotency-Key": "us3-cancel-terminal"},
        )
        assert order.status_code == 201

    await _change(apps, token, subscription_id, "cancel")

    async with client_for(apps.order) as order_client:
        rejected = await order_client.post(
            f"/api/v1/subscriptions/{subscription_id}/pause",
            headers=auth_header(token),
        )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "CONFLICT"

    # Купленные данные остаются доступными после отмены подписки.
    async with client_for(apps.delivery) as delivery_client:
        download = await delivery_client.get(
            f"/api/v1/datasets/{DEMO_DATASET}/download",
            params={"format": "CSV"},
            headers=auth_header(token),
        )
    assert download.status_code == 200
    assert download.content
