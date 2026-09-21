"""Контрактный тест review: оценка 1–5 и последний отзыв в рейтинге (T060)."""

from __future__ import annotations

import pytest

from support import DEMO_DATASET, Apps, auth_header, client_for, token_for

pytestmark = pytest.mark.contract


async def test_review_rating_uses_latest_only(apps: Apps) -> None:
    """Число отзывов не ограничено, но в рейтинг идёт последний (FR-010)."""
    async with client_for(apps.review) as client:
        token = await token_for(apps)
        headers = auth_header(token)
        dataset = "ds_retail-sales"

        first = await client.post(
            "/api/v1/reviews",
            json={"datasetId": dataset, "rating": 1, "text": "Плохо"},
            headers=headers,
        )
        assert first.status_code == 201
        latest = await client.post(
            "/api/v1/reviews",
            json={"datasetId": dataset, "rating": 5, "text": "Отлично"},
            headers=headers,
        )
        assert latest.status_code == 201

        rating = await client.get(f"/api/v1/datasets/{dataset}/rating", headers=headers)
        assert rating.status_code == 200
        assert rating.json()["rating"] == 5.0

        listing = await client.get(
            "/api/v1/reviews", params={"datasetId": dataset}, headers=headers
        )
        assert listing.status_code == 200
        assert listing.json()["pagination"]["total"] == 2
    assert len(apps.review_events.published) == 2


async def test_review_rating_bounds(apps: Apps) -> None:
    """Оценка вне 1–5 отклоняется единым конвертом (FR-010)."""
    async with client_for(apps.review) as client:
        token = await token_for(apps)
        response = await client.post(
            "/api/v1/reviews",
            json={"datasetId": DEMO_DATASET, "rating": 6},
            headers=auth_header(token),
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_review_requires_auth(apps: Apps) -> None:
    """Отзывы доступны только аутентифицированному покупателю."""
    async with client_for(apps.review) as client:
        response = await client.post(
            "/api/v1/reviews", json={"datasetId": DEMO_DATASET, "rating": 5}
        )
    assert response.status_code == 401
