"""Демонстрационная аутентификация: Bearer-токены и машинные ключи.

Токены подписываются HMAC (без внешних JWT-зависимостей), а машинные ключи
хранятся только в виде SHA-256-хеша — открытый ключ не сохраняется.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

USER_ID_HEADER = "X-User-Id"
API_KEY_HEADER = "X-Api-Key"
TOKEN_PREFIX = "usr_"


def hash_api_key(api_key: str) -> str:
    """Вернуть детерминированный SHA-256-хеш машинного ключа."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def encode_token(user_id: str, secret: str) -> str:
    """Выпустить Bearer-токен вида ``usr_<payload>.<signature>``."""
    payload = base64.urlsafe_b64encode(user_id.encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256)
    return f"{TOKEN_PREFIX}{payload}.{signature.hexdigest()}"


def decode_token(token: str, secret: str) -> str | None:
    """Проверить подпись токена и вернуть ``user_id`` либо ``None``."""
    if not token.startswith(TOKEN_PREFIX) or "." not in token:
        return None
    payload, _, signature = token[len(TOKEN_PREFIX) :].partition(".")
    if not payload or not signature:
        return None
    expected = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256)
    if not hmac.compare_digest(expected.hexdigest(), signature):
        return None
    padded = payload + "=" * (-len(payload) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def bearer_user_id(authorization: str | None, secret: str) -> str | None:
    """Извлечь ``user_id`` из заголовка ``Authorization: Bearer ...``."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return decode_token(token.strip(), secret)


def user_id_from_headers(
    authorization: str | None,
    x_user_id: str | None,
    secret: str,
) -> str | None:
    """Определить покупателя по Bearer-токену или внутреннему ``X-User-Id``."""
    return bearer_user_id(authorization, secret) or (x_user_id or None)


def mask_email(email: str) -> str:
    """Замаскировать email до вида ``***@domain`` (FR-028, SC-009)."""
    _, _, domain = email.partition("@")
    if not domain:
        return "***"
    return f"***@{domain}"


__all__ = [
    "API_KEY_HEADER",
    "TOKEN_PREFIX",
    "USER_ID_HEADER",
    "bearer_user_id",
    "decode_token",
    "encode_token",
    "hash_api_key",
    "mask_email",
    "user_id_from_headers",
]
