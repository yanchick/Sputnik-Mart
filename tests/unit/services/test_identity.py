"""Unit-тесты identity: токены, аутентификация и выпуск ключей (T061)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from identity.api_keys import generate_api_key, issue_api_key
from identity.repository import PiiVault, User
from identity.service import build_profile, list_subscriptions

from observability.auth import (
    decode_token,
    encode_token,
    hash_api_key,
    mask_email,
)
from support import FakeAddSession

pytestmark = pytest.mark.unit

SECRET = "unit-secret"


class _StubOrder:
    """Order-заглушка для чтения подписок по HTTP (M6)."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        self.calls.append((path, dict(headers or {})))
        return self.payload

    async def post_json(
        self,
        path: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        return {}


def test_token_round_trip() -> None:
    token = encode_token("us_demo_buyer", SECRET)

    assert token.startswith("usr_")
    assert decode_token(token, SECRET) == "us_demo_buyer"


def test_token_tamper_rejected() -> None:
    token = encode_token("us_demo_buyer", SECRET)

    assert decode_token(token + "00", SECRET) is None
    assert decode_token(token, "other-secret") is None
    assert decode_token("not-a-token", SECRET) is None


def test_mask_email() -> None:
    assert mask_email("buyer@sputnik.demo") == "***@sputnik.demo"
    assert mask_email("invalid") == "***"


def test_generate_api_key_shape() -> None:
    key_id, prefix, plaintext = generate_api_key()

    assert key_id.startswith("ak_")
    assert plaintext.startswith("sk_")
    assert plaintext.startswith(prefix)
    assert hash_api_key(plaintext) == hash_api_key(plaintext)


async def test_issue_api_key_stores_hash_only() -> None:
    session = FakeAddSession()

    api_key, plaintext = await issue_api_key(session, "us_demo_buyer")  # type: ignore[arg-type]

    assert session.added == [api_key]
    assert api_key.user_id == "us_demo_buyer"
    assert api_key.key_hash == hash_api_key(plaintext)
    assert api_key.key_hash != plaintext
    assert api_key.scopes == ["read", "download"]


def test_build_profile_masks_email() -> None:
    now = datetime.now(UTC)
    user = User(user_id="us_x", display_name="X", status="ACTIVE", created_at=now)
    pii = PiiVault(user_id="us_x", email_enc=b"x@sputnik.demo", phone_enc=b"+7", key_ref="kms://x")

    profile = build_profile(user, pii)

    assert profile.email == "***@sputnik.demo"
    assert profile.userId == "us_x"


@pytest.mark.parametrize("bad_token", ["", "usr_", "usr_a.", "bearer abc"])
def test_decode_token_rejects_malformed(bad_token: str) -> None:
    assert decode_token(bad_token, SECRET) is None


async def test_list_subscriptions_reads_order_service() -> None:
    """M6: identity получает подписки из order-сервиса, не читая его таблицу."""
    order = _StubOrder(
        {
            "data": [
                {
                    "subscriptionId": "sub_1",
                    "userId": "us_1",
                    "datasetId": "ds_weather-stations",
                    "intervalSec": 300,
                    "status": "SUB_ACTIVE",
                    "startedAt": "2026-01-01T00:00:00+00:00",
                }
            ],
            "pagination": {},
        }
    )

    views = await list_subscriptions(order, "us_1")

    assert [view.subscriptionId for view in views] == ["sub_1"]
    assert views[0].status.value == "SUB_ACTIVE"
    path, headers = order.calls[0]
    assert path == "/api/v1/subscriptions"
    assert headers == {"X-User-Id": "us_1"}
