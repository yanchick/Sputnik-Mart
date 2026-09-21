"""Контрактный тест identity: login, /users/me, API-ключи (T056)."""

from __future__ import annotations

import pytest

from support import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    Apps,
    auth_header,
    client_for,
    login,
    token_for,
)

pytestmark = pytest.mark.contract


async def test_login_and_me(apps: Apps) -> None:
    """Вход по демо-аккаунту и профиль с замаскированным email (FR-001)."""
    async with client_for(apps.identity) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tokenType"] == "Bearer"
        assert body["user"]["email"] == "***@sputnik.demo"

        me = await client.get("/api/v1/users/me", headers=auth_header(body["accessToken"]))
        assert me.status_code == 200
        assert me.json()["userId"] == "us_demo_buyer"


async def test_login_rejects_wrong_password(apps: Apps) -> None:
    """Неверный пароль — 401 в едином конверте без утечки PII."""
    async with client_for(apps.identity) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"}
        )
    assert response.status_code == 401
    payload = response.json()["error"]
    assert payload["code"] == "UNAUTHORIZED"
    assert "requestId" in payload


async def test_registration_is_not_supported(apps: Apps) -> None:
    """Самостоятельная регистрация отсутствует (FR-001)."""
    async with client_for(apps.identity) as client:
        response = await client.post(
            "/api/v1/auth/register", json={"email": "x@y.z", "password": "pw"}
        )
    assert response.status_code in {404, 405}


async def test_api_key_issue_and_revoke(apps: Apps) -> None:
    """Выпуск ключа даёт доступ, после отзыва ключ не работает (FR-002)."""
    async with client_for(apps.identity) as client:
        token = await login(client)
        created = await client.post(
            "/api/v1/users/us_demo_buyer/api-keys", headers=auth_header(token)
        )
        assert created.status_code == 201
        issued = created.json()
        assert issued["apiKey"].startswith("sk_")
        assert "key_hash" not in issued

        async with client_for(apps.delivery) as delivery:
            allowed = await delivery.get(
                "/api/v1/datasets/ds_weather-stations/download",
                headers={"X-Api-Key": issued["apiKey"]},
            )
            assert allowed.status_code != 401

        revoked = await client.delete(
            f"/api/v1/users/us_demo_buyer/api-keys/{issued['keyId']}",
            headers=auth_header(token),
        )
        assert revoked.status_code == 204

        async with client_for(apps.delivery) as delivery:
            denied = await delivery.get(
                "/api/v1/datasets/ds_weather-stations/download",
                headers={"X-Api-Key": issued["apiKey"]},
            )
            assert denied.status_code == 401


async def test_subscriptions_listed_for_self(apps: Apps) -> None:
    """Кабинет отдаёт подписки покупателя и запрещает чужие (FR-008)."""
    token = await token_for(apps)
    async with client_for(apps.order) as order_client:
        await order_client.post(
            "/api/v1/subscriptions",
            json={"datasetId": "ds_air-quality", "intervalSec": 600},
            headers=auth_header(token),
        )

    async with client_for(apps.identity) as client:
        response = await client.get(
            "/api/v1/users/us_demo_buyer/subscriptions", headers=auth_header(token)
        )
        assert response.status_code == 200
        assert response.json()["data"]

        forbidden = await client.get(
            "/api/v1/users/us_demo_analyst/subscriptions", headers=auth_header(token)
        )
        assert forbidden.status_code == 403


def test_demo_password_constant() -> None:
    """Демо-пароль фиксирован для предсозданных аккаунтов."""
    assert DEMO_PASSWORD == "demo"
