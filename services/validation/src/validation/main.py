"""Точка входа validation: bronze → silver + отчёт качества (T116/T117)."""

from __future__ import annotations

import asyncio
import io
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import get_settings
from observability import configure_logging, get_logger

from .idempotency import silver_key
from .quality_report import build_reports, write_reports
from .validator import CleanBatch, clean_readings

_log = get_logger(__name__)


def silver_parquet_bytes(frame: pd.DataFrame) -> bytes:
    """Сериализовать silver-фрейм в Parquet (PyArrow)."""
    serializable = frame.copy()
    if "dt" in serializable.columns:
        serializable["dt"] = serializable["dt"].astype(str)
    table = pa.Table.from_pandas(serializable, preserve_index=False)
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


async def write_silver(
    store: Any,
    bucket: str,
    batch: CleanBatch,
    dt: date,
) -> dict[str, str]:
    """Идемпотентно записать silver-партиции по датасетам и вернуть ключи."""
    written: dict[str, str] = {}
    if batch.frame.empty:
        return written
    for dataset_id in batch.frame["dataset_id"].dropna().unique().tolist():
        subset = batch.frame[batch.frame["dataset_id"] == dataset_id].reset_index(drop=True)
        key = f"{silver_key(str(dataset_id), dt)}/part-00000.parquet"
        await store.put_bytes(bucket, key, silver_parquet_bytes(subset), "application/octet-stream")
        written[str(dataset_id)] = key
    return written


async def run_validation(
    records: Sequence[Mapping[str, Any]],
    *,
    store: Any,
    bucket: str,
    dt: date | None = None,
) -> tuple[CleanBatch, dict[str, str], dict[str, dict[str, Any]]]:
    """Очистить bronze, записать silver и отчёт; пустой вход не падает (FR-032)."""
    report_date = dt or datetime.now(UTC).date()
    batch = clean_readings(records)
    keys = await write_silver(store, bucket, batch, report_date)
    reports = build_reports(batch, report_date)
    await write_reports(store, bucket, report_date, reports)
    _log.info(
        "validation_done",
        silver_objects=len(keys),
        quarantine=len(batch.quarantine),
        datasets=len(reports),
    )
    return batch, keys, reports


async def _run_once() -> None:
    from db import create_object_store

    settings = get_settings()
    store = create_object_store(
        endpoint_url=settings.minio.endpoint,
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name=settings.minio.region,
    )
    today = datetime.now(UTC).date()
    records: list[dict[str, Any]] = []
    for key in await store.list_keys(settings.minio.lake_bucket, "bronze/"):
        if not key.endswith(".ndjson"):
            continue
        body = await store.get_bytes(settings.minio.lake_bucket, key)
        for line in body.decode("utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    await run_validation(records, store=store, bucket=settings.minio.lake_bucket, dt=today)


def main() -> None:
    """Разовый прогон validation по bronze за сегодня (профиль adv)."""
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="validation")
    asyncio.run(_run_once())


__all__ = ["main", "run_validation", "silver_parquet_bytes", "write_silver"]
