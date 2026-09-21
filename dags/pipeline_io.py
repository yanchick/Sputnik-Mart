"""Общие I/O-хелперы Airflow DAGов контент-конвейера (T126–T128)."""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger("sputnik.pipeline")


def object_store() -> Any:
    """Создать MinIO/S3-клиент из настроек окружения."""
    from config import get_settings
    from db import create_object_store

    settings = get_settings()
    return create_object_store(
        endpoint_url=settings.minio.endpoint,
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name=settings.minio.region,
    )


def lake_bucket() -> str:
    """Имя бакета озера."""
    from config import get_settings

    return get_settings().minio.lake_bucket


def clickhouse_client() -> Any:
    """Создать ClickHouse-клиент из настроек окружения."""
    from config import get_settings
    from db.clickhouse import create_client

    settings = get_settings()
    return create_client(
        host=settings.clickhouse.host,
        port=settings.clickhouse.port,
        username=settings.clickhouse.user,
        password=settings.clickhouse.password,
        database=settings.clickhouse.database,
    )


async def read_ndjson_prefix(store: Any, bucket: str, prefix: str) -> list[dict[str, Any]]:
    """Прочитать все NDJSON-объекты под префиксом."""
    records: list[dict[str, Any]] = []
    for key in await store.list_keys(bucket, prefix):
        if not key.endswith(".ndjson"):
            continue
        body = await store.get_bytes(bucket, key)
        for line in body.decode("utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


async def write_ndjson(store: Any, bucket: str, key: str, records: list[Any]) -> str | None:
    """Записать список записей как NDJSON; ``None`` — если записей нет."""
    if not records:
        return None
    body = "\n".join(json.dumps(record, ensure_ascii=False, default=str) for record in records)
    await store.put_bytes(bucket, key, body.encode("utf-8"), "application/x-ndjson")
    return key


def on_failure(context: dict[str, Any]) -> None:
    """Колбэк падения шага: структурированный лог для разбора инцидента."""
    task = context.get("task_instance")
    _log.error(
        "pipeline_task_failed task_id=%s dag_id=%s run_id=%s",
        getattr(task, "task_id", "unknown"),
        getattr(task, "dag_id", "unknown"),
        context.get("run_id"),
    )


__all__ = [
    "clickhouse_client",
    "lake_bucket",
    "object_store",
    "on_failure",
    "read_ndjson_prefix",
    "write_ndjson",
]
