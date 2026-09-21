"""Интеграционный тест «подписка → доставка → переподключение без дублей» (T137)."""

from __future__ import annotations

import pytest

from support import DEMO_DATASET, Apps, auth_header, client_for, parse_sse, token_for

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


async def _stream(apps: Apps, token: str, subscription_id: str) -> list[dict[str, object]]:
    async with client_for(apps.delivery) as client:
        response = await client.get(
            f"/api/v1/streams/{subscription_id}", headers=auth_header(token)
        )
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


def _reading_ids(events: list[dict[str, object]]) -> list[str]:
    return [str(event["id"]) for event in events if event["event"] == "reading"]


async def test_subscription_stream_reconnect_has_no_duplicates(apps: Apps) -> None:
    token = await token_for(apps)
    subscription_id = await _subscribe(apps, token)

    first = await _stream(apps, token, subscription_id)
    second = await _stream(apps, token, subscription_id)

    first_ids = _reading_ids(first)
    second_ids = _reading_ids(second)

    assert first_ids, "первое подключение должно доставить свежие чтения"
    assert second_ids == [], "переподключение не должно повторять доставленные readingId"
    assert len(first_ids) == len(set(first_ids))
    assert not set(first_ids) & set(second_ids)


async def test_stream_belongs_to_subscriber_only(apps: Apps) -> None:
    token = await token_for(apps)
    subscription_id = await _subscribe(apps, token)

    async with client_for(apps.delivery) as client:
        response = await client.get(
            f"/api/v1/streams/{subscription_id}",
            headers={"X-Api-Key": "sk_demo_analyst_key"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
