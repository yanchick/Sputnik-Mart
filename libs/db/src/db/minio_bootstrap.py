"""Bootstrap MinIO: бакеты lake/samples/exports и префиксы слоёв."""

from __future__ import annotations

from collections.abc import Sequence

from .objectstore import (
    PREFIX_BRONZE,
    PREFIX_EXPORTS,
    PREFIX_PARTNER,
    PREFIX_REPORTS,
    PREFIX_SAMPLES,
    PREFIX_SILVER,
    AsyncObjectStore,
)

DEFAULT_LAKE_PREFIXES: tuple[str, ...] = (
    PREFIX_BRONZE,
    PREFIX_SILVER,
    PREFIX_REPORTS,
    PREFIX_EXPORTS,
    PREFIX_SAMPLES,
    PREFIX_PARTNER,
)


async def bootstrap_buckets(store: AsyncObjectStore, buckets: Sequence[str]) -> list[str]:
    """Создать отсутствующие бакеты; вернуть список созданных."""
    created: list[str] = []
    for bucket in buckets:
        if await store.ensure_bucket(bucket):
            created.append(bucket)
    return created


async def bootstrap_prefixes(
    store: AsyncObjectStore,
    bucket: str,
    prefixes: Sequence[str] = DEFAULT_LAKE_PREFIXES,
) -> list[str]:
    """Создать маркеры ``{prefix}/.keep`` в бакете; вернуть список префиксов."""
    for prefix in prefixes:
        await store.put_bytes(bucket, f"{prefix}/.keep", b"", content_type="text/plain")
    return list(prefixes)


async def bootstrap_minio(
    store: AsyncObjectStore,
    buckets: Sequence[str],
    *,
    lake_bucket: str,
    prefixes: Sequence[str] = DEFAULT_LAKE_PREFIXES,
) -> dict[str, list[str]]:
    """Создать бакеты и слоистые префиксы озера."""
    created = await bootstrap_buckets(store, buckets)
    prefix_list = await bootstrap_prefixes(store, lake_bucket, prefixes)
    return {"buckets_created": created, "prefixes": prefix_list}


__all__ = [
    "DEFAULT_LAKE_PREFIXES",
    "bootstrap_buckets",
    "bootstrap_minio",
    "bootstrap_prefixes",
]
