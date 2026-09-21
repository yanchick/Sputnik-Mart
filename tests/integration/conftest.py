"""Общие фикстуры интеграционных тестов контент-конвейера (US2)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _docker_available() -> bool:
    try:
        from testcontainers.core.docker_client import DockerClient

        return bool(DockerClient().client.ping())
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Признак доступности Docker-демона (иначе интеграционные тесты skip)."""
    return _docker_available()


@pytest.fixture(scope="session")
def minio_store(docker_available: bool) -> Iterator[Any]:
    """Поднять MinIO и вернуть клиент с созданным бакетом ``lake``."""
    if not docker_available:
        pytest.skip("Docker daemon недоступен — integration test пропущен")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import HttpWaitStrategy

    from db import create_object_store

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
        asyncio.run(store.ensure_bucket("lake"))
        yield store


@pytest.fixture(scope="session")
def clickhouse_client(docker_available: bool) -> Iterator[Any]:
    """Поднять ClickHouse, применить DDL и вернуть клиент базы ``sputnik``."""
    if not docker_available:
        pytest.skip("Docker daemon недоступен — integration test пропущен")
    from testcontainers.community.clickhouse import ClickHouseContainer

    from db.clickhouse import create_client

    def _statements(sql: str) -> list[str]:
        uncommented = "\n".join(
            line for line in sql.splitlines() if not line.strip().startswith("--")
        )
        return [statement.strip() for statement in uncommented.split(";") if statement.strip()]

    ddl_dir = REPO_ROOT / "infra" / "clickhouse"
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
        for filename in ("01_fact_readings.sql", "02_marts.sql"):
            for statement in _statements((ddl_dir / filename).read_text(encoding="utf-8")):
                asyncio.run(client.command(statement))
        asyncio.run(client.close())

        typed_client = create_client(
            host=host,
            port=port,
            username=str(container.username),
            password=str(container.password),
            database="sputnik",
        )
        yield typed_client
        asyncio.run(typed_client.close())
