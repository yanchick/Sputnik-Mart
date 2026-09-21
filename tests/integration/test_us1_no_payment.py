"""Интеграционный тест отказа скачивания без оплаты (T067)."""

from __future__ import annotations

import pytest

from support import Apps, auth_header, client_for, token_for

pytestmark = pytest.mark.integration

UNPAID_DATASET = "ds_traffic-flow"


async def test_download_denied_without_payment(apps: Apps) -> None:
    """Без оплаченного заказа — 403, а не данные (FR-007)."""
    async with client_for(apps.delivery) as client:
        token = await token_for(apps)
        response = await client.get(
            f"/api/v1/datasets/{UNPAID_DATASET}/download",
            headers=auth_header(token),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert response.json()["error"]["requestId"]


async def test_download_denied_for_machine_key_without_payment(apps: Apps) -> None:
    """Машинный ключ без оплаты аутентифицирован, но получает 403 (FR-036)."""
    async with client_for(apps.delivery) as client:
        response = await client.get(
            f"/api/v1/datasets/{UNPAID_DATASET}/download",
            headers={"X-Api-Key": "sk_demo_analyst_key"},
        )

    assert response.status_code == 403


async def test_unauthorized_without_credentials(apps: Apps) -> None:
    """Без учётных данных — 401 в едином конверте."""
    async with client_for(apps.delivery) as client:
        response = await client.get(f"/api/v1/datasets/{UNPAID_DATASET}/download")

    assert response.status_code == 401
