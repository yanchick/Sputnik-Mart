"""Rate-limit ``429`` + ``Retry-After`` + ``X-RateLimit-*`` (T090, FR-038)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from db.redis import RateLimiter as RedisLimiter

STREAM_PREFIX = "/api/v1/streams/"
DOWNLOAD_SUFFIX = "/download"


def rate_limit_scope(path: str) -> str:
    """Отдельная квота для долгоживущих потоков и выгрузок.

    SSE-соединение держится минутами, поэтому поток и выгрузка не должны
    расходовать общий лимит обычных REST-запросов покупателя.
    """
    if path.startswith(STREAM_PREFIX):
        return "stream"
    if path.endswith(DOWNLOAD_SUFFIX):
        return "export"
    return "api"


def scoped_rate_limit_key(base_key: str, path: str) -> str:
    """Ключ лимита с учётом области пути."""
    return f"{base_key}:{rate_limit_scope(path)}"


@dataclass(frozen=True)
class RateLimitResult:
    """Результат проверки лимита частоты."""

    allowed: bool
    retry_after: int
    remaining: int
    reset_after: int


class RateLimiter(Protocol):
    """Абстракция лимитера (Redis или in-memory для тестов)."""

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Проверить и учесть запрос по ключу."""
        ...


class InMemoryRateLimiter:
    """Фиксированное окно в памяти процесса (для тестов и локальных прогонов)."""

    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, float]] = {}

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        count, reset_at = self._windows.get(key, (0, now + window_seconds))
        if now >= reset_at:
            count, reset_at = 0, now + window_seconds
        count += 1
        self._windows[key] = (count, reset_at)
        reset_after = max(int(reset_at - now), 1)
        if count > limit:
            return RateLimitResult(False, reset_after, 0, reset_after)
        return RateLimitResult(True, 0, max(limit - count, 0), reset_after)


class RedisRateLimiter:
    """Лимитер на Redis с общим окном между репликами gateway."""

    def __init__(self, redis_url: str) -> None:
        from db.redis import create_redis

        self._client = create_redis(redis_url)
        self._limiter = RedisLimiter(self._client)

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        allowed, retry_after = await self._limiter.check(key, limit, window_seconds)
        if not allowed:
            return RateLimitResult(False, retry_after, 0, retry_after)
        return RateLimitResult(True, 0, max(limit - 1, 0), window_seconds)


def create_rate_limiter(redis_url: str | None) -> RateLimiter:
    """Выбрать лимитер: Redis при настроенном URL, иначе in-memory."""
    if redis_url:
        return RedisRateLimiter(redis_url)
    return InMemoryRateLimiter()


__all__ = [
    "DOWNLOAD_SUFFIX",
    "STREAM_PREFIX",
    "InMemoryRateLimiter",
    "RateLimitResult",
    "RateLimiter",
    "RedisRateLimiter",
    "create_rate_limiter",
    "rate_limit_scope",
    "scoped_rate_limit_key",
]
