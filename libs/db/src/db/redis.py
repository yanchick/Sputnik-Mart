"""Redis-клиент для rate-limit и идемпотентности (redis-py, async)."""

from __future__ import annotations

from typing import Final

from redis.asyncio import Redis, from_url

IDEMPOTENCY_PREFIX: Final = "idempotency:"
RATE_LIMIT_PREFIX: Final = "ratelimit:"


def create_redis(url: str) -> Redis:
    """Создать асинхронный Redis-клиент с текстовым протоколом."""
    return from_url(url, encoding="utf-8", decode_responses=True)


async def close_redis(client: Redis) -> None:
    """Закрыть соединение с Redis."""
    await client.aclose()


class IdempotencyStore:
    """Идемпотентность по ключу через атомарный ``SET NX``."""

    def __init__(self, client: Redis, prefix: str = IDEMPOTENCY_PREFIX) -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def reserve(self, key: str, ttl_seconds: int) -> bool:
        """Зарезервировать ключ; ``True`` — первый раз, ``False`` — повтор."""
        stored = await self._client.set(self._key(key), "1", ex=ttl_seconds, nx=True)
        return bool(stored)

    async def is_seen(self, key: str) -> bool:
        """Проверить, встречался ли ключ (без побочных эффектов)."""
        return bool(await self._client.exists(self._key(key)))

    async def forget(self, key: str) -> None:
        """Снять резерв ключа (например, при откате операции)."""
        await self._client.delete(self._key(key))


class RateLimiter:
    """Rate-limit по фиксированному окну с временем до повтора."""

    def __init__(self, client: Redis, prefix: str = RATE_LIMIT_PREFIX) -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Вернуть ``(allowed, retry_after)`` для ключа за окно.

        ``allowed`` — можно ли выполнить запрос; ``retry_after`` — секунды до
        сброса счётчика при отказе.
        """
        redis_key = self._key(key)
        current = await self._client.incr(redis_key)
        if current == 1:
            await self._client.expire(redis_key, window_seconds)
        if current > limit:
            ttl = await self._client.ttl(redis_key)
            return False, max(ttl, 1)
        return True, 0


__all__ = [
    "IDEMPOTENCY_PREFIX",
    "RATE_LIMIT_PREFIX",
    "IdempotencyStore",
    "RateLimiter",
    "close_redis",
    "create_redis",
]
