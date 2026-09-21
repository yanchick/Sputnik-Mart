"""Контрактный тест SSE ``GET /streams/{subscriptionId}`` (T134, FR-022)."""

from __future__ import annotations

import pytest

from support import (
    DEMO_DATASET,
    Apps,
    auth_header,
    client_for,
    parse_sse,
    token_for,
)

pytestmark = pytest.mark.contract

DEMO_API_KEY = "sk_demo_buyer_key"


async def _new_subscription(apps: Apps) -> tuple[str, str]:
    """Оформить подписку и вернуть ``(token, subscriptionId)``."""
    async with client_for(apps.order) as order_client:
        token = await token_for(apps)
        response = await order_client.post(
            "/api/v1/subscriptions",
            json={"datasetId": DEMO_DATASET, "intervalSec": 300},
            headers=auth_header(token),
        )
        assert response.status_code == 201, response.text
        return token, response.json()["subscriptionId"]


async def test_stream_requires_authentication(apps: Apps) -> None:
    async with client_for(apps.delivery) as client:
        response = await client.get("/api/v1/streams/sub_missing")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_stream_unknown_subscription_returns_404(apps: Apps) -> None:
    token, _ = await _new_subscription(apps)
    async with client_for(apps.delivery) as client:
        response = await client.get("/api/v1/streams/sub_unknown", headers=auth_header(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_stream_emits_reading_frames_with_unique_ids(apps: Apps) -> None:
    token, subscription_id = await _new_subscription(apps)
    async with client_for(apps.delivery) as client:
        response = await client.get(
            f"/api/v1/streams/{subscription_id}", headers=auth_header(token)
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert any(event["event"] == "ping" for event in events)
    reading_ids = [event["id"] for event in events if event["event"] == "reading"]
    assert reading_ids
    assert len(reading_ids) == len(set(reading_ids))


async def test_stream_accepts_api_key(apps: Apps) -> None:
    _token, subscription_id = await _new_subscription(apps)
    async with client_for(apps.delivery) as client:
        response = await client.get(
            f"/api/v1/streams/{subscription_id}", headers={"X-Api-Key": DEMO_API_KEY}
        )

    assert response.status_code == 200
    assert "reading" in response.text
