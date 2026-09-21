"""DAG ``sync_provider_exports``: партнёрские CSV → bronze → silver (T128, FR-033).

Партнёрская выгрузка проходит те же слои и проверки, что и потоковые данные;
несоответствие схеме отбраковывается и не попадает в аналитику.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from pipeline_io import lake_bucket, object_store, on_failure, write_ndjson

DEFAULT_START = datetime(2026, 9, 1, tzinfo=UTC)

DEFAULT_ARGS: dict[str, Any] = {
    "owner": "sputnik",
    "retries": 3,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "on_failure_callback": on_failure,
}


def _has_partner_files(**_context: Any) -> bool:
    """Сенсор: в озере есть партнёрские CSV."""

    async def _run() -> bool:
        store = object_store()
        keys = await store.list_keys(lake_bucket(), "partner/")
        return any(key.endswith(".csv") for key in keys)

    return asyncio.run(_run())


def _sync_exports(**_context: Any) -> dict[str, Any]:
    """CSV поставщиков → bronze, затем общая валидация в silver."""
    from validation.main import run_validation
    from validation.partner import parse_partner_csv

    async def _run() -> dict[str, Any]:
        store = object_store()
        bucket = lake_bucket()
        day = datetime.now(UTC).date()
        keys = [key for key in await store.list_keys(bucket, "partner/") if key.endswith(".csv")]
        records: list[dict[str, Any]] = []
        providers: set[str] = set()
        for key in keys:
            parts = key.split("/")
            provider = parts[1] if len(parts) > 1 else "pv_unknown"
            providers.add(provider)
            body = await store.get_bytes(bucket, key)
            readings = parse_partner_csv(body.decode("utf-8"), provider)
            records.extend(readings)
            await write_ndjson(
                store,
                bucket,
                f"bronze/{provider}/{day.isoformat()}/partner-{len(readings):05d}.ndjson",
                readings,
            )
        _batch, silver_keys, reports = await run_validation(
            records, store=store, bucket=bucket, dt=day
        )
        return {
            "providers": sorted(providers),
            "readings": len(records),
            "silver": len(silver_keys),
            "reports": len(reports),
        }

    return asyncio.run(_run())


with DAG(
    dag_id="sync_provider_exports",
    description="Партнёрские выгрузки через конвейер bronze → silver",
    schedule="@daily",
    start_date=DEFAULT_START,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["content", "partner", "us2"],
) as dag:
    wait_for_files = PythonSensor(
        task_id="wait_for_partner_files",
        python_callable=_has_partner_files,
        mode="reschedule",
        poke_interval=60,
        timeout=1800,
    )
    sync_exports = PythonOperator(task_id="sync_exports", python_callable=_sync_exports)

    wait_for_files >> sync_exports


__all__ = ["dag"]
