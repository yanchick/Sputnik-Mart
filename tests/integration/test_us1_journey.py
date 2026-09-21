"""Интеграционный тест пути US1 через gateway (T066)."""

from __future__ import annotations

import pytest

from support import DEMO_DATASET, DEMO_EMAIL, DEMO_PASSWORD, Apps, auth_header

pytestmark = pytest.mark.integration


async def test_us1_journey_login_catalog_buy_download_review(apps: Apps) -> None:
    """«вход → каталог → карточка → покупка → скачивание → отзыв» (SC-002)."""
    client = apps.gateway_client

    login = await client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert login.status_code == 200
    token = login.json()["accessToken"]
    headers = {**auth_header(token), "Idempotency-Key": "us1-journey-1"}

    catalog = await client.get("/api/v1/datasets", headers=headers)
    assert catalog.status_code == 200
    assert any(item["datasetId"] == DEMO_DATASET for item in catalog.json()["data"])

    card = await client.get(f"/api/v1/datasets/{DEMO_DATASET}", headers=headers)
    assert card.status_code == 200
    schema = await client.get(f"/api/v1/datasets/{DEMO_DATASET}/schema", headers=headers)
    assert schema.status_code == 200
    sample = await client.get(f"/api/v1/datasets/{DEMO_DATASET}/sample", headers=headers)
    assert sample.status_code == 200

    order = await client.post("/api/v1/orders", json={"datasetId": DEMO_DATASET}, headers=headers)
    assert order.status_code == 201
    assert order.json()["status"] == "ORDER_PAID"

    download = await client.get(
        f"/api/v1/datasets/{DEMO_DATASET}/download",
        params={"format": "CSV"},
        headers=headers,
    )
    assert download.status_code == 200
    assert download.content

    review = await client.post(
        "/api/v1/reviews",
        json={"datasetId": DEMO_DATASET, "rating": 4, "text": "Хорошие данные"},
        headers=headers,
    )
    assert review.status_code == 201
    rating = await client.get(f"/api/v1/datasets/{DEMO_DATASET}/rating", headers=headers)
    assert rating.status_code == 200

    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    user_id = me.json()["userId"]

    orders = await client.get("/api/v1/orders", headers=headers)
    assert orders.status_code == 200
    downloads = await client.get("/api/v1/downloads", headers=headers)
    assert downloads.status_code == 200
    assert downloads.json()["data"]

    subscriptions = await client.get(f"/api/v1/users/{user_id}/subscriptions", headers=headers)
    assert subscriptions.status_code == 200

    request_id = download.headers.get("X-Request-Id")
    assert request_id is not None and request_id.startswith("req_")
