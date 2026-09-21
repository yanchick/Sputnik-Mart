"""Точка входа transform: silver из MinIO → gold в ClickHouse (T118–T120)."""

from __future__ import annotations

import asyncio
import io
import json
import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from config import get_settings
from db import create_object_store
from db.clickhouse import create_client
from observability import configure_logging, get_logger

from .transform import transform_batch

_log = get_logger(__name__)


async def _read_silver(store: Any, bucket: str, prefix: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for key in await store.list_keys(bucket, prefix):
        if not key.endswith(".parquet"):
            continue
        body = await store.get_bytes(bucket, key)
        frames.append(pq.read_table(io.BytesIO(body)).to_pandas())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


async def _read_reports(store: Any, bucket: str, dt: Any) -> dict[str, dict[str, Any]]:
    key = f"reports/quality/{dt.isoformat()}/report.json"
    try:
        body = await store.get_bytes(bucket, key)
    except Exception:  # отчёт может отсутствовать в пустом прогоне (FR-032)
        return {}
    payload = json.loads(body.decode("utf-8"))
    return {str(k): dict(v) for k, v in payload.get("datasets", {}).items()}


async def run_transform(dt: Any | None = None) -> dict[str, int]:
    """Прочитать silver за дату и загрузить gold-витрины идемпотентно."""
    settings = get_settings()
    day = dt or datetime.now(UTC).date()
    store = create_object_store(
        endpoint_url=settings.minio.endpoint,
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name=settings.minio.region,
    )
    frame = await _read_silver(store, settings.minio.lake_bucket, "silver/")
    reports = await _read_reports(store, settings.minio.lake_bucket, day)
    client = create_client(
        host=settings.clickhouse.host,
        port=settings.clickhouse.port,
        username=settings.clickhouse.user,
        password=settings.clickhouse.password,
        database=settings.clickhouse.database,
    )
    try:
        counts = await transform_batch(client, frame, reports, reviews=[], dt=day)
    finally:
        await client.close()
    _log.info("transform_done", day=str(day), **counts)
    return counts


def main() -> None:
    """Разовый прогон transform (профиль adv)."""
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="transform")
    asyncio.run(run_transform())


__all__ = ["main", "run_transform"]
