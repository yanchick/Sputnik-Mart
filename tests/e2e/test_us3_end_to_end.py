"""E2E-тест сквозного сценария подписки (T153, FR-035, SC-006).

«вход → подписка → живой поток → график → пауза/возобновление → отмена» через
api-gateway; идентификаторы кадров уникальны, переподключение не даёт дублей.
"""

from __future__ import annotations

import pytest
from bokeh.models import ColumnDataSource
from web_vitrina.client_sse import StreamFrame
from web_vitrina.pages.stream import update_chart

from support import DEMO_DATASET, DEMO_EMAIL, DEMO_PASSWORD, Apps, auth_header, parse_sse

pytestmark = pytest.mark.e2e


async def _login(apps: Apps) -> dict[str, str]:
    response = await apps.gateway_client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return auth_header(response.json()["accessToken"])


async def test_us3_end_to_end_subscription_stream(apps: Apps) -> None:
    headers = await _login(apps)
    created = await apps.gateway_client.post(
        "/api/v1/subscriptions",
        json={"datasetId": DEMO_DATASET, "intervalSec": 300},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    subscription_id = created.json()["subscriptionId"]
    assert created.json()["status"] == "SUB_ACTIVE"

    first = await apps.gateway_client.get(f"/api/v1/streams/{subscription_id}", headers=headers)
    assert first.status_code == 200
    first_events = parse_sse(first.text)
    first_ids = [event["id"] for event in first_events if event["event"] == "reading"]
    assert first_ids and len(first_ids) == len(set(first_ids))

    # Живой график строится из тех же кадров.
    frames = [
        StreamFrame(event=str(event["event"]), event_id=event["id"], data=dict(event["data"]))
        for event in first_events
    ]
    source = ColumnDataSource(data={"x": [], "y": []})
    assert update_chart(source, frames, offset=0) == len(first_ids)

    # Переподключение: доставленные readingId не повторяются.
    second = await apps.gateway_client.get(f"/api/v1/streams/{subscription_id}", headers=headers)
    second_ids = [event["id"] for event in parse_sse(second.text) if event["event"] == "reading"]
    assert second_ids == []
    assert not set(first_ids) & set(second_ids)

    paused = await apps.gateway_client.post(
        f"/api/v1/subscriptions/{subscription_id}/pause", headers=headers
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "SUB_PAUSED"
    blocked = await apps.gateway_client.get(f"/api/v1/streams/{subscription_id}", headers=headers)
    assert blocked.status_code == 403

    resumed = await apps.gateway_client.post(
        f"/api/v1/subscriptions/{subscription_id}/resume", headers=headers
    )
    assert resumed.json()["status"] == "SUB_ACTIVE"

    cancelled = await apps.gateway_client.post(
        f"/api/v1/subscriptions/{subscription_id}/cancel", headers=headers
    )
    assert cancelled.json()["status"] == "SUB_CANCELLED"
