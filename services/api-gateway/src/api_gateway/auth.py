"""Bearer-auth покупателя и ``X-Api-Key`` для машинных операций (T089)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from observability import API_KEY_HEADER, encode_token, hash_api_key
from observability.auth import bearer_user_id

PUBLIC_PATHS = frozenset({"/healthz", "/docs", "/redoc", "/openapi.json"})
PUBLIC_PREFIXES = ("/api/v1/auth/login",)
# Read-only Quality-page доступна без входа: это агрегированные показатели
# качества демо-данных. Запись ``/quality/recalculate`` остаётся защищённой.
PUBLIC_READ_PREFIXES = ("/api/v1/quality",)


@dataclass(frozen=True)
class Principal:
    """Аутентифицированный субъект запроса к gateway."""

    user_id: str | None
    api_key: str | None
    kind: str

    @property
    def rate_limit_key(self) -> str:
        """Ключ лимита частоты: покупатель или хеш машинного ключа."""
        if self.user_id is not None:
            return f"user:{self.user_id}"
        return f"key:{hash_api_key(self.api_key or '')}"


def is_public(path: str, method: str = "GET") -> bool:
    """Публичные маршруты, не требующие аутентификации.

    Чтение Quality-page (``GET /api/v1/quality``) открыто, а запись
    (``POST /api/v1/quality/recalculate``) — нет.
    """
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return True
    return method.upper() in {"GET", "HEAD"} and path.startswith(PUBLIC_READ_PREFIXES)


def is_machine_path(path: str) -> bool:
    """Маршруты, доступные по ``X-Api-Key`` (выгрузка и поток)."""
    if path.endswith("/download") and path.startswith("/api/v1/datasets/"):
        return True
    return path.startswith("/api/v1/streams/")


def resolve_principal(request: Request, secret: str) -> Principal | None:
    """Определить покупателя по Bearer-токену или машинному ключу."""
    user_id = bearer_user_id(request.headers.get("Authorization"), secret)
    if user_id is not None:
        return Principal(user_id=user_id, api_key=None, kind="buyer")
    api_key = request.headers.get(API_KEY_HEADER)
    if api_key:
        return Principal(user_id=None, api_key=api_key, kind="machine")
    return None


def issue_demo_token(user_id: str, secret: str) -> str:
    """Выпустить токен (используется в тестах и клиенты)."""
    return encode_token(user_id, secret)


__all__ = [
    "PUBLIC_PATHS",
    "PUBLIC_PREFIXES",
    "PUBLIC_READ_PREFIXES",
    "Principal",
    "is_machine_path",
    "is_public",
    "issue_demo_token",
    "resolve_principal",
]
