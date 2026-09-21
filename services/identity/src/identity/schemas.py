"""Pydantic v2-схемы identity: вход, профиль, машинные ключи."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from contracts import SubscriptionStatus


class LoginRequest(BaseModel):
    """Учётные данные предсозданного демонстрационного аккаунта."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class UserProfile(BaseModel):
    """Публичный профиль покупателя; email возвращается замаскированным."""

    model_config = ConfigDict(extra="forbid")

    userId: str
    displayName: str
    status: str
    email: str
    createdAt: datetime


class LoginResponse(BaseModel):
    """Ответ успешного входа с Bearer-токеном."""

    model_config = ConfigDict(extra="forbid")

    accessToken: str
    tokenType: str = "Bearer"
    expiresIn: int = 3600
    user: UserProfile


class ApiKeyView(BaseModel):
    """Метаданные машинного ключа без секрета."""

    model_config = ConfigDict(extra="forbid")

    keyId: str
    keyPrefix: str
    scopes: list[str]
    createdAt: datetime
    revokedAt: datetime | None = None


class ApiKeyCreated(BaseModel):
    """Ответ выпуска ключа: открытый ключ показывается один раз."""

    model_config = ConfigDict(extra="forbid")

    keyId: str
    keyPrefix: str
    apiKey: str
    scopes: list[str]
    createdAt: datetime


class ApiKeyResolveRequest(BaseModel):
    """Тело внутренней проверки машинного ключа (M6)."""

    model_config = ConfigDict(extra="forbid")

    apiKey: str = Field(min_length=1)


class ApiKeyResolution(BaseModel):
    """Результат проверки ключа: владелец или ``None`` для недействительного."""

    model_config = ConfigDict(extra="forbid")

    userId: str | None = None


class SubscriptionView(BaseModel):
    """Подписка покупателя в личном кабинете."""

    model_config = ConfigDict(extra="forbid")

    subscriptionId: str
    userId: str
    datasetId: str
    intervalSec: int
    status: SubscriptionStatus
    startedAt: datetime


__all__ = [
    "ApiKeyCreated",
    "ApiKeyResolution",
    "ApiKeyResolveRequest",
    "ApiKeyView",
    "LoginRequest",
    "LoginResponse",
    "SubscriptionView",
    "UserProfile",
]
