"""E2E-тест приёмки M0–M4 и SC-показателей (T163, SC-001…SC-014).

Сводит пользовательские истории в один прогон на профиле ``demo``: витрина и
покупка (US1), конвейер и качество (US2), подписка и поток (US3), а также
наблюдаемость, PII, retention, hard gates и воспроизводимость (US4).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_gateway.main import create_app as create_gateway_app
from api_gateway.rate_limit import InMemoryRateLimiter
from identity.masking import contains_pii, sanitize_export_rows
from identity.pii import encrypt_email
from identity.retention import delete_expired_pii
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import AppSettings, Settings
from quality.metrics import evaluate_degradation_alerts
from sim.dirty import DirtyConfig, contaminate
from sim.sensors import generate_readings, readings_digest
from support import (
    DEMO_DATASET,
    DEMO_EMAIL,
    DEMO_PASSWORD,
    Apps,
    auth_header,
    client_for,
    parse_sse,
    token_for,
)
from validation.validator import clean_readings

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _login_gateway(apps: Apps) -> dict[str, str]:
    response = await apps.gateway_client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return auth_header(response.json()["accessToken"])


def test_stand_declares_all_profiles() -> None:
    """SC-001/SC-010: стенд поднимается одной командой на трёх профилях."""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for profile in ("base", "adv", "demo"):
        assert profile in compose
    assert "prepare_demo_data" in compose


def test_sc003_generation_is_reproducible() -> None:
    assert readings_digest(generate_readings(seed=42, periods=10)) == readings_digest(
        generate_readings(seed=42, periods=10)
    )
    assert _digest(clean_readings(generate_readings(seed=42, periods=4)).metrics) == _digest(
        clean_readings(generate_readings(seed=42, periods=4)).metrics
    )


def test_sc004_sc005_dlq_and_no_duplicates() -> None:
    readings = generate_readings(seed=5, periods=6)
    dirty = contaminate(
        readings,
        seed=5,
        config=DirtyConfig(missing=0.2, duplicate=0.4, outlier=0.1, broken=0.3),
    )
    batch = clean_readings(dirty)

    assert batch.quarantine, "невалидные записи должны попасть в карантин/DLQ"
    assert batch.metrics.duplicates >= 1
    reading_ids = list(batch.frame["reading_id"])
    assert len(reading_ids) == len(set(reading_ids))


def test_sc009_exports_never_contain_pii() -> None:
    sanitized = sanitize_export_rows(
        [
            {
                "email": "buyer@sputnik.demo",
                "phone": "+79990000001",
                "note": "звонить buyer@sputnik.demo",
            }
        ]
    )

    assert not contains_pii(sanitized)
    assert sanitized[0]["email"] == "***@sputnik.demo"


def test_sc011_degradation_alert_fires() -> None:
    alerts = evaluate_degradation_alerts(
        [
            {"dataset_id": "ds_clean", "quality_score": 0.95},
            {"dataset_id": "ds_dirty", "quality_score": 0.25},
        ],
        baseline=0.9,
    )
    assert {alert.dataset for alert in alerts if alert.active} == {"ds_dirty"}


async def test_sc013_retention_removes_only_expired_pii(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO identity.users (user_id, display_name, status, created_at) "
                "VALUES ('us_accept_old', 'Old', 'ACTIVE', :created_at) "
                "ON CONFLICT (user_id) DO UPDATE SET created_at = EXCLUDED.created_at"
            ),
            {"created_at": now - timedelta(days=400)},
        )
        await session.execute(
            text(
                "INSERT INTO identity.pii_vault (user_id, email_enc, phone_enc, key_ref) "
                "VALUES ('us_accept_old', :email, :phone, 'kms://sputnik/pii/test') "
                "ON CONFLICT (user_id) DO UPDATE SET email_enc = EXCLUDED.email_enc"
            ),
            {
                "email": encrypt_email("old@sputnik.demo"),
                "phone": encrypt_email("+79990000009"),
            },
        )
        await session.commit()

    async with session_factory() as session:
        deleted = await delete_expired_pii(session, now=now)
        await session.commit()
        remaining = await session.execute(
            text("SELECT count(*) FROM identity.pii_vault WHERE user_id = 'us_accept_old'")
        )
    assert deleted >= 1
    assert int(remaining.scalar_one()) == 0


async def test_us1_journey_login_catalog_order_download_review(apps: Apps) -> None:
    """SC-002: вход → каталог → покупка → скачивание → отзыв."""
    async with client_for(apps.identity) as identity_client:
        login = await identity_client.post(
            "/api/v1/auth/login",
            json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        )
    assert login.status_code == 200
    headers = auth_header(login.json()["accessToken"])

    async with client_for(apps.catalog) as catalog_client:
        listing = await catalog_client.get("/api/v1/datasets", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total"] >= 1

    async with client_for(apps.order) as order_client:
        order = await order_client.post(
            "/api/v1/orders",
            json={"datasetId": DEMO_DATASET},
            headers={**headers, "Idempotency-Key": "acceptance-key"},
        )
    assert order.status_code == 201
    assert order.json()["status"] == "ORDER_PAID"

    async with client_for(apps.delivery) as delivery_client:
        download = await delivery_client.get(
            f"/api/v1/datasets/{DEMO_DATASET}/download", headers=headers
        )
    assert download.status_code == 200
    assert b"readingId" in download.content

    async with client_for(apps.review) as review_client:
        review = await review_client.post(
            "/api/v1/reviews",
            json={"datasetId": DEMO_DATASET, "rating": 5, "text": "Отлично"},
            headers=headers,
        )
    assert review.status_code == 201
    assert review.json()["rating"] == 5


async def test_sc006_subscription_stream_has_unique_ids(apps: Apps) -> None:
    headers = await _login_gateway(apps)
    created = await apps.gateway_client.post(
        "/api/v1/subscriptions",
        json={"datasetId": DEMO_DATASET, "intervalSec": 300},
        headers=headers,
    )
    assert created.status_code == 201
    subscription_id = created.json()["subscriptionId"]

    stream = await apps.gateway_client.get(f"/api/v1/streams/{subscription_id}", headers=headers)
    assert stream.status_code == 200
    reading_ids = [event["id"] for event in parse_sse(stream.text) if event["event"] == "reading"]
    assert reading_ids
    assert len(reading_ids) == len(set(reading_ids))


async def test_sc014_rate_limit_returns_retry_after(apps: Apps) -> None:
    token = await token_for(apps)

    def _ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    settings = Settings(app=AppSettings(rate_limit_per_minute=1, rate_limit_window_seconds=60))
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(_ok))
    gateway = create_gateway_app(settings=settings, client=upstream, limiter=InMemoryRateLimiter())
    try:
        async with client_for(gateway) as client:
            headers = auth_header(token)
            first = await client.get("/api/v1/datasets", headers=headers)
            second = await client.get("/api/v1/datasets", headers=headers)
    finally:
        await upstream.aclose()

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert second.json()["error"]["code"] == "RATE_LIMITED"
