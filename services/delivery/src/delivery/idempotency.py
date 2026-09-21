"""Идемпотентность доставки: дедупликация по ``readingId`` (T144, FR-023).

At-least-once доставка неизбежно повторяет кадры, поэтому уникальность
гарантируется на стороне получателя: ключ ``stream:reading:{readingId}``
резервируется атомарно (Redis ``SET NX``), а повторный ``readingId``
отбрасывается. В профиле ``base`` без Redis используется in-memory-реализация.
"""

from __future__ import annotations

from typing import Protocol

from db.redis import IdempotencyStore

DEFAULT_DEDUP_TTL_SECONDS = 86_400
READING_DEDUP_PREFIX = "stream:reading:"


class ReadingDeduplicator(Protocol):
    """Абстракция дедупликации кадров живого потока."""

    async def reserve(self, reading_id: str) -> bool:
        """Вернуть ``True``, если ``readingId`` встречается впервые."""
        ...


class InMemoryReadingDeduplicator:
    """Дедупликатор в памяти процесса (тесты и профиль ``base``)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def reserve(self, reading_id: str) -> bool:
        """Пометить ``readingId`` доставленным; повтор вернёт ``False``."""
        if reading_id in self._seen:
            return False
        self._seen.add(reading_id)
        return True


class RedisReadingDeduplicator:
    """Дедупликатор на Redis с TTL, общий между репликами delivery."""

    def __init__(
        self,
        store: IdempotencyStore,
        ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    async def reserve(self, reading_id: str) -> bool:
        """Зарезервировать ``readingId`` атомарно через ``SET NX``."""
        return await self._store.reserve(f"{READING_DEDUP_PREFIX}{reading_id}", self._ttl_seconds)


def create_reading_deduplicator(
    redis_url: str | None, ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS
) -> ReadingDeduplicator:
    """Выбрать Redis-дедупликатор при настроенном URL, иначе in-memory."""
    if not redis_url:
        return InMemoryReadingDeduplicator()
    from db.redis import create_redis

    return RedisReadingDeduplicator(IdempotencyStore(create_redis(redis_url)), ttl_seconds)


__all__ = [
    "DEFAULT_DEDUP_TTL_SECONDS",
    "READING_DEDUP_PREFIX",
    "InMemoryReadingDeduplicator",
    "ReadingDeduplicator",
    "RedisReadingDeduplicator",
    "create_reading_deduplicator",
]
