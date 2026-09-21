"""Общая библиотека ``db`` проекта «Спутник Данные».

Фабрики подключений и bootstrap для Postgres, Redis, Kafka, ClickHouse, Mongo,
MinIO и MongoDB-индексов. Библиотека не выполняет I/O на этапе импорта.
"""

from __future__ import annotations

from .clickhouse import AsyncClickHouseClient, create_client
from .kafka import create_consumer, create_producer, produce_json, stream_json
from .minio_bootstrap import (
    DEFAULT_LAKE_PREFIXES,
    bootstrap_buckets,
    bootstrap_minio,
    bootstrap_prefixes,
)
from .mongo import close_mongo, create_mongo_client, get_database, ping
from .mongo_indexes import (
    PROVIDER_META_COLLECTION,
    ensure_provider_meta_indexes,
    provider_meta_indexes,
)
from .objectstore import (
    PREFIX_BRONZE,
    PREFIX_EXPORTS,
    PREFIX_PARTNER,
    PREFIX_REPORTS,
    PREFIX_SAMPLES,
    PREFIX_SILVER,
    AsyncObjectStore,
    create_object_store,
)
from .postgres import (
    NAMING_CONVENTION,
    Base,
    create_engine,
    create_session_factory,
    dispose_engine,
    session_scope,
)
from .redis import (
    IDEMPOTENCY_PREFIX,
    RATE_LIMIT_PREFIX,
    IdempotencyStore,
    RateLimiter,
    close_redis,
    create_redis,
)

__all__ = [
    "DEFAULT_LAKE_PREFIXES",
    "IDEMPOTENCY_PREFIX",
    "NAMING_CONVENTION",
    "PREFIX_BRONZE",
    "PREFIX_EXPORTS",
    "PREFIX_PARTNER",
    "PREFIX_REPORTS",
    "PREFIX_SAMPLES",
    "PREFIX_SILVER",
    "PROVIDER_META_COLLECTION",
    "RATE_LIMIT_PREFIX",
    "AsyncClickHouseClient",
    "AsyncObjectStore",
    "Base",
    "IdempotencyStore",
    "RateLimiter",
    "bootstrap_buckets",
    "bootstrap_minio",
    "bootstrap_prefixes",
    "close_mongo",
    "close_redis",
    "create_client",
    "create_consumer",
    "create_engine",
    "create_mongo_client",
    "create_object_store",
    "create_producer",
    "create_redis",
    "create_session_factory",
    "dispose_engine",
    "ensure_provider_meta_indexes",
    "get_database",
    "ping",
    "produce_json",
    "provider_meta_indexes",
    "session_scope",
    "stream_json",
]
