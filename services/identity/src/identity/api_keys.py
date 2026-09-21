"""Выпуск и отзыв машинных ключей доступа к данным (T072, FR-002, FR-036)."""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from observability.auth import hash_api_key

from .repository import ApiKey, add_api_key, revoke_api_key

API_KEY_PREFIX = "sk_"
DEFAULT_SCOPES: tuple[str, ...] = ("read", "download")


def generate_api_key() -> tuple[str, str, str]:
    """Сгенерировать ``(key_id, key_prefix, plaintext)`` машинного ключа."""
    key_id = f"ak_{uuid.uuid4().hex[:12]}"
    plaintext = f"{API_KEY_PREFIX}{secrets.token_urlsafe(24)}"
    return key_id, plaintext[:11], plaintext


async def issue_api_key(
    session: AsyncSession,
    user_id: str,
    *,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> tuple[ApiKey, str]:
    """Выпустить ключ и вернуть ORM-запись вместе с открытым ключом (один раз)."""
    key_id, key_prefix, plaintext = generate_api_key()
    api_key = ApiKey(
        key_id=key_id,
        user_id=user_id,
        key_prefix=key_prefix,
        key_hash=hash_api_key(plaintext),
        scopes=list(scopes),
    )
    await add_api_key(session, api_key)
    return api_key, plaintext


async def revoke_key(session: AsyncSession, user_id: str, key_id: str) -> bool:
    """Отозвать ключ пользователя (необратимо)."""
    return await revoke_api_key(session, user_id, key_id)


__all__ = [
    "API_KEY_PREFIX",
    "DEFAULT_SCOPES",
    "generate_api_key",
    "issue_api_key",
    "revoke_key",
]
