"""DAG ``ingest_readings``: pull_bronze → validate → silver → transform → load_gold (T126).

Идемпотентен при повторном запуске: bronze дедуплицируется по ``readingId``,
silver/ClickHouse пишутся upsert-ом по детерминированным ключам (FR-024).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from pipeline_io import (
    clickhouse_client,
    lake_bucket,
    object_store,
    on_failure,
    read_ndjson_prefix,
    write_ndjson,
)

DEFAULT_START = datetime(2026, 9, 1, tzinfo=UTC)

DEFAULT_ARGS: dict[str, Any] = {
    "owner": "sputnik",
    "retries": 3,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "on_failure_callback": on_failure,
}


def _pull_bronze(**_context: Any) -> dict[str, Any]:
    """Ограниченный pull из Kafka в bronze (at-least-once + дедупликация)."""
    from ingestion.main import run_ingestion

    max_messages = int(os.environ.get("INGEST_MAX_MESSAGES", "500"))
    timeout = float(os.environ.get("INGEST_TIMEOUT_SEC", "30"))

    async def _run() -> Any:
        try:
            return await asyncio.wait_for(run_ingestion(max_messages=max_messages), timeout=timeout)
        except TimeoutError:
            return None

    result = asyncio.run(_run())
    if result is None:
        return {"written": 0, "duplicates": 0, "dead": 0}
    return {"written": result.written, "duplicates": result.duplicates, "dead": len(result.dead)}


def _validate(**_context: Any) -> dict[str, Any]:
    """Bronze → silver + отчёт качества (идемпотентно)."""
    from validation.main import run_validation

    async def _run() -> dict[str, Any]:
        store = object_store()
        bucket = lake_bucket()
        records = await read_ndjson_prefix(store, bucket, "bronze/")
        _batch, keys, reports = await run_validation(records, store=store, bucket=bucket)
        return {"input": len(records), "datasets": sorted(keys), "reports": len(reports)}

    return asyncio.run(_run())


def _silver(**_context: Any) -> dict[str, Any]:
    """Подтвердить/перезаписать silver-партиции по данным bronze."""
    from validation.main import run_validation

    async def _run() -> dict[str, Any]:
        store = object_store()
        bucket = lake_bucket()
        records = await read_ndjson_prefix(store, bucket, "bronze/")
        _batch, keys, _reports = await run_validation(records, store=store, bucket=bucket)
        return {"datasets": sorted(keys), "objects": len(keys)}

    return asyncio.run(_run())


def _transform(**_context: Any) -> dict[str, Any]:
    """Silver → staging gold: факты чтений и прогноз часовых рядов."""
    from transform.gold_readings import build_fact_rows, forecast_series

    async def _run() -> dict[str, Any]:
        import pandas as pd
        import pyarrow.parquet as pq

        store = object_store()
        bucket = lake_bucket()
        frames: list[Any] = []
        for key in await store.list_keys(bucket, "silver/"):
            if key.endswith(".parquet"):
                body = await store.get_bytes(bucket, key)
                frames.append(pq.read_table(io.BytesIO(body)).to_pandas())
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        day = datetime.now(UTC).date().isoformat()
        rows = build_fact_rows(frame)
        forecasts = forecast_series(frame)
        await write_ndjson(store, bucket, f"gold/staging/{day}/fact_readings.ndjson", rows)
        await write_ndjson(store, bucket, f"gold/staging/{day}/forecasts.ndjson", forecasts)
        return {"facts": len(rows), "forecasts": len(forecasts)}

    return asyncio.run(_run())


def _load_gold(**_context: Any) -> dict[str, Any]:
    """Загрузка fact_readings, прогноза и mart_quality_daily в ClickHouse (upsert)."""
    from transform.gold_quality import build_quality_rows, load_quality_mart
    from transform.gold_readings import build_forecast_rows, load_forecasts, load_gold_readings

    async def _run() -> dict[str, Any]:
        store = object_store()
        bucket = lake_bucket()
        day = datetime.now(UTC).date()
        staging = await read_ndjson_prefix(store, bucket, "gold/staging/")
        facts = [
            [
                row.get("reading_id"),
                row.get("station_id"),
                row.get("provider_id"),
                row.get("metric"),
                row.get("value"),
                row.get("unit"),
                row.get("lat"),
                row.get("lon"),
                row.get("measured_at"),
                row.get("received_at"),
                row.get("dt") or day,
            ]
            for row in staging
            if row.get("reading_id")
        ]
        forecast_rows = build_forecast_rows(
            [row for row in staging if row.get("forecast_value") is not None]
        )
        reports: dict[str, Any] = {}
        try:
            body = await store.get_bytes(bucket, f"reports/quality/{day.isoformat()}/report.json")
            reports = json.loads(body.decode("utf-8")).get("datasets", {})
        except Exception:
            reports = {}
        client = clickhouse_client()
        try:
            loaded = await load_gold_readings(client, facts, day)
            forecasts = await load_forecasts(client, forecast_rows)
            quality = await load_quality_mart(client, build_quality_rows(reports))
        finally:
            await client.close()
        return {
            "fact_readings": loaded,
            "forecasts": forecasts,
            "mart_quality_daily": quality,
        }

    return asyncio.run(_run())


def _wait_for_bronze(**_context: Any) -> bool:
    """Сенсор свежести: в озере есть хотя бы один bronze-объект."""

    async def _run() -> bool:
        store = object_store()
        keys = await store.list_keys(lake_bucket(), "bronze/")
        return any(key.endswith(".ndjson") for key in keys)

    return asyncio.run(_run())


with DAG(
    dag_id="ingest_readings",
    description="Bronze → silver → gold конвейер чтений датчиков",
    schedule="@hourly",
    start_date=DEFAULT_START,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["content", "us2"],
) as dag:
    wait_for_bronze = PythonSensor(
        task_id="wait_for_bronze",
        python_callable=_wait_for_bronze,
        mode="reschedule",
        poke_interval=30,
        timeout=600,
    )
    pull_bronze = PythonOperator(task_id="pull_bronze", python_callable=_pull_bronze)
    validate = PythonOperator(task_id="validate", python_callable=_validate)
    silver = PythonOperator(task_id="silver", python_callable=_silver)
    transform = PythonOperator(task_id="transform", python_callable=_transform)
    load_gold = PythonOperator(task_id="load_gold", python_callable=_load_gold)

    wait_for_bronze >> pull_bronze >> validate >> silver >> transform >> load_gold


def reference_date() -> datetime:
    """Дата по умолчанию для ручных прогонов."""
    return datetime.now(UTC)


__all__ = ["dag", "reference_date"]
