"""Foundational-интеграционные тесты стека через testcontainers (T055).

Тесты поднимают реальные Postgres/Redis/ClickHouse/Mongo/MinIO/Redpanda. Если
Docker-демон недоступен, тесты помечаются ``skip`` и не валят suite. Все тесты
помечены маркером ``integration``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from db import (
    IdempotencyStore,
    RateLimiter,
    bootstrap_minio,
    close_mongo,
    close_redis,
    create_client,
    create_consumer,
    create_mongo_client,
    create_object_store,
    create_producer,
    create_redis,
    ensure_provider_meta_indexes,
    get_database,
    produce_json,
    stream_json,
)
from db.clickhouse import AsyncClickHouseClient

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "libs" / "db" / "migrations"
CLICKHOUSE_DIR = REPO_ROOT / "infra" / "clickhouse"


def _docker_available() -> bool:
    try:
        from testcontainers.core.docker_client import DockerClient

        return bool(DockerClient().client.ping())
    except Exception:
        return False


DOCKER_AVAILABLE = _docker_available()


def _require_docker() -> None:
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker daemon недоступен — integration test пропущен")


def _alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _statements(sql: str) -> list[str]:
    uncommented = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    return [statement.strip() for statement in uncommented.split(";") if statement.strip()]


def test_postgres_migrations_up_and_down(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_docker()
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        dsn = container.get_connection_url()
        monkeypatch.setenv("POSTGRES_URL", dsn)

        command.upgrade(_alembic_config(), "head")
        tables = asyncio.run(_postgres_tables(dsn))
        assert {"users", "pii_vault", "api_keys"} <= tables["identity"]
        assert {"providers", "datasets", "dataset_fields"} <= tables["catalog"]
        assert {"orders", "subscriptions", "downloads"} <= tables["orders"]
        assert {"reviews"} <= tables["reviews"]

        command.downgrade(_alembic_config(), "base")
        after = asyncio.run(_postgres_tables(dsn))
        assert after == {}


async def _postgres_tables(dsn: str) -> dict[str, set[str]]:
    import asyncpg

    connection = await asyncpg.connect(dsn.replace("+asyncpg", ""))
    try:
        rows = await connection.fetch(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('identity', 'catalog', 'orders', 'reviews')"
        )
    finally:
        await connection.close()

    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["table_schema"]), set()).add(str(row["table_name"]))
    return grouped


def test_redis_idempotency_and_rate_limit() -> None:
    _require_docker()
    from testcontainers.community.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        client = create_redis(f"redis://{host}:{port}/0")
        result = asyncio.run(_redis_checks(client))
        assert result == ("reserved", "repeated", "rate-limited")


async def _redis_checks(client: Any) -> tuple[str, str, str]:
    store = IdempotencyStore(client)
    assert await store.reserve("order:1", 60) is True
    first = "repeated" if not await store.reserve("order:1", 60) else "leaked"

    limiter = RateLimiter(client)
    assert (await limiter.check("user:1", limit=2, window_seconds=60))[0] is True
    assert (await limiter.check("user:1", limit=2, window_seconds=60))[0] is True
    allowed, retry_after = await limiter.check("user:1", limit=2, window_seconds=60)
    assert allowed is False
    assert retry_after >= 1

    await close_redis(client)
    return "reserved", first, "rate-limited"


def test_clickhouse_ddl_bootstraps_facts_and_marts() -> None:
    _require_docker()
    from testcontainers.community.clickhouse import ClickHouseContainer

    with ClickHouseContainer("clickhouse/clickhouse-server:24.3") as container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(8123))
        client = create_client(
            host=host,
            port=port,
            username=str(container.username),
            password=str(container.password),
            database=str(container.dbname),
        )
        try:
            for filename in ("01_fact_readings.sql", "02_marts.sql"):
                for statement in _statements((CLICKHOUSE_DIR / filename).read_text("utf-8")):
                    asyncio.run(client.command(statement))
            names = asyncio.run(_clickhouse_tables(client))
        finally:
            asyncio.run(client.close())

        assert {
            "fact_readings",
            "mv_readings_hourly",
            "mart_sales_daily",
            "mart_quality_daily",
            "mart_sentiment_daily",
        } <= names


async def _clickhouse_tables(client: AsyncClickHouseClient) -> set[str]:
    result = await client.execute("SELECT name FROM system.tables WHERE database = 'sputnik'")
    return {str(row[0]) for row in result.result_rows}


def test_mongo_indexes_for_provider_meta() -> None:
    _require_docker()
    from testcontainers.community.mongodb import MongoDbContainer

    with MongoDbContainer("mongo:7") as container:
        url = container.get_connection_url()
        names = asyncio.run(_mongo_setup(url))
        assert {
            "uq_provider_meta_provider_id",
            "ix_provider_meta_text",
            "ix_provider_meta_device_station",
            "ix_provider_meta_status",
        } <= names


async def _mongo_setup(url: str) -> set[str]:
    client = create_mongo_client(url)
    try:
        database = get_database(client, "catalog_nosql")
        await ensure_provider_meta_indexes(database)
        info: Mapping[str, Any] = await database["provider_meta"].index_information()
        return set(info)
    finally:
        await close_mongo(client)


def test_minio_bootstrap_buckets_and_prefixes() -> None:
    _require_docker()
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import HttpWaitStrategy

    container = (
        DockerContainer("quay.io/minio/minio:RELEASE.2024-06-13T22-53-53Z")
        .with_exposed_ports(9000)
        .with_env("MINIO_ROOT_USER", "minioadmin")
        .with_env("MINIO_ROOT_PASSWORD", "minioadmin")
        .with_command("server /data --console-address :9001")
        .waiting_for(HttpWaitStrategy(9000, "/minio/health/live"))
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(9000)
        store = create_object_store(
            endpoint_url=f"http://{host}:{port}",
            aws_access_key_id="minioadmin",
            aws_secret_access_key="minioadmin",
        )
        result = asyncio.run(_minio_setup(store))
        assert set(result["buckets_created"]) == {"lake", "samples", "exports"}
        assert "bronze/.keep" in result["keys"]
        assert "partner/.keep" in result["keys"]


async def _minio_setup(store: Any) -> dict[str, list[str]]:
    result = await bootstrap_minio(store, ("lake", "samples", "exports"), lake_bucket="lake")
    keys = await store.list_keys("lake")
    return {"buckets_created": result["buckets_created"], "keys": keys}


def test_redpanda_produce_and_consume() -> None:
    _require_docker()
    from testcontainers.community.kafka import RedpandaContainer

    with RedpandaContainer("redpandadata/redpanda:v24.1.7") as container:
        bootstrap = container.get_bootstrap_server()
        payload = asyncio.run(_kafka_round_trip(bootstrap))
        assert payload == {"readingId": "rd_test", "stationId": "st_test"}


async def _kafka_round_trip(bootstrap: str) -> dict[str, Any]:
    producer = create_producer(bootstrap)
    await producer.start()
    try:
        await produce_json(
            producer,
            "sensors.readings.v1",
            {"readingId": "rd_test", "stationId": "st_test"},
            key="st_test",
        )
    finally:
        await producer.stop()

    consumer = create_consumer(["sensors.readings.v1"], "foundational-test", bootstrap)
    await consumer.start()
    try:
        async for value in stream_json(consumer, max_messages=1):
            return dict(value)
    finally:
        await consumer.stop()
    raise AssertionError("сообщение не доставлено")


@pytest.fixture(autouse=True)
def _integration_guard() -> Iterator[None]:
    _require_docker()
    yield
