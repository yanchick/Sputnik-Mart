"""Сервис аутентификации: только предсозданные аккаунты, Bearer-токены (T070)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from observability import USER_ID_HEADER, ApiError, encode_token
from observability.auth import mask_email
from observability.pii import DEFAULT_PII_KEY, decrypt_pii
from service_client import ServiceClient

from . import repository as repo
from .schemas import (
    ApiKeyCreated,
    ApiKeyView,
    LoginResponse,
    SubscriptionView,
    UserProfile,
)

INVALID_CREDENTIALS = "Неверный email или пароль"
NO_REGISTRATION = "Самостоятельная регистрация не поддерживается"


def _email_of(pii: repo.PiiVault, key: str = DEFAULT_PII_KEY) -> str:
    return decrypt_pii(pii.email_enc, key)


def build_profile(user: repo.User, pii: repo.PiiVault, key: str = DEFAULT_PII_KEY) -> UserProfile:
    """Собрать публичный профиль с замаскированным email."""
    return UserProfile(
        userId=user.user_id,
        displayName=user.display_name,
        status=user.status,
        email=mask_email(_email_of(pii, key)),
        createdAt=user.created_at,
    )


async def login(
    session: AsyncSession, email: str, password: str, settings: Settings
) -> LoginResponse:
    """Аутентифицировать предсозданный демо-аккаунт и выпустить токен."""
    found = await repo.find_user_by_email(session, email, settings.app.pii_encryption_key)
    if found is None or password != settings.app.demo_password:
        raise ApiError(401, "UNAUTHORIZED", INVALID_CREDENTIALS)
    user, pii = found
    if user.status != repo.ACTIVE_STATUS:
        raise ApiError(403, "FORBIDDEN", "Аккаунт заблокирован")
    return LoginResponse(
        accessToken=encode_token(user.user_id, settings.app.auth_secret),
        user=build_profile(user, pii, settings.app.pii_encryption_key),
    )


async def get_profile(
    session: AsyncSession, user_id: str, key: str = DEFAULT_PII_KEY
) -> UserProfile:
    """Вернуть профиль покупателя по идентификатору."""
    user = await repo.get_user(session, user_id)
    pii = await repo.get_pii(session, user_id)
    if user is None or pii is None:
        raise ApiError(404, "NOT_FOUND", "Покупатель не найден")
    return build_profile(user, pii, key)


async def list_subscriptions(order: ServiceClient, user_id: str) -> list[SubscriptionView]:
    """Вернуть подписки покупателя из order-сервиса — владельца ``subscriptions`` (M6)."""
    payload = await order.get_json("/api/v1/subscriptions", headers={USER_ID_HEADER: user_id})
    rows = payload.get("data", []) if isinstance(payload, Mapping) else payload
    return [
        SubscriptionView(
            subscriptionId=str(row["subscriptionId"]),
            userId=str(row["userId"]),
            datasetId=str(row["datasetId"]),
            intervalSec=int(row["intervalSec"]),
            status=str(row["status"]),
            startedAt=_as_utc(row["startedAt"]),
        )
        for row in rows
    ]


def _as_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ApiError(500, "INTERNAL_ERROR", "Некорректная метка времени подписки") from None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise ApiError(500, "INTERNAL_ERROR", "Некорректная метка времени подписки")


def to_api_key_view(api_key: repo.ApiKey) -> ApiKeyView:
    """Представление ключа без секрета."""
    return ApiKeyView(
        keyId=api_key.key_id,
        keyPrefix=api_key.key_prefix,
        scopes=list(api_key.scopes),
        createdAt=api_key.created_at,
        revokedAt=api_key.revoked_at,
    )


def to_api_key_created(api_key: repo.ApiKey, plaintext: str) -> ApiKeyCreated:
    """Представление только что выпущенного ключа с открытым секретом."""
    return ApiKeyCreated(
        keyId=api_key.key_id,
        keyPrefix=api_key.key_prefix,
        apiKey=plaintext,
        scopes=list(api_key.scopes),
        createdAt=api_key.created_at,
    )


__all__ = [
    "INVALID_CREDENTIALS",
    "NO_REGISTRATION",
    "build_profile",
    "get_profile",
    "list_subscriptions",
    "login",
    "to_api_key_created",
    "to_api_key_view",
]
