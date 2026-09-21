"""DAG ``refresh_quality``: пересчёт qualityScore + сенсор свежести (T127)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from pipeline_io import clickhouse_client, lake_bucket, object_store, on_failure

DEFAULT_START = datetime(2026, 9, 1, tzinfo=UTC)

DEFAULT_ARGS: dict[str, Any] = {
    "owner": "sputnik",
    "retries": 3,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "on_failure_callback": on_failure,
}


def _latest_report_day() -> str | None:
    """Дата последнего доступного отчёта качества в озере."""

    async def _run() -> str | None:
        store = object_store()
        keys = await store.list_keys(lake_bucket(), "reports/quality/")
        days = sorted(
            {
                key.split("/")[2]
                for key in keys
                if key.endswith("report.json") and len(key.split("/")) > 3
            }
        )
        return days[-1] if days else None

    return asyncio.run(_run())


def _read_reports() -> dict[str, Any]:
    """Прочитать отчёты за последнюю дату."""

    async def _run() -> dict[str, Any]:
        store = object_store()
        bucket = lake_bucket()
        keys = await store.list_keys(bucket, "reports/quality/")
        days = sorted(
            {
                key.split("/")[2]
                for key in keys
                if key.endswith("report.json") and len(key.split("/")) > 3
            }
        )
        if not days:
            return {}
        try:
            body = await store.get_bytes(bucket, f"reports/quality/{days[-1]}/report.json")
        except Exception:
            return {}
        return dict(json.loads(body.decode("utf-8")).get("datasets", {}))

    return asyncio.run(_run())


def _recalculate(**_context: Any) -> dict[str, Any]:
    """Пересчитать qualityScore и опубликовать лаг/свежесть (идемпотентный upsert)."""
    from config import get_settings
    from db.postgres import create_engine, create_session_factory
    from observability import encode_token
    from quality.runtime_metrics import READINGS_TOPIC, refresh_runtime_metrics
    from quality.service import recalculate_quality_scores
    from service_client import HttpServiceClient

    reports = _read_reports()
    if not reports:
        return {"updated": 0}

    async def _run() -> dict[str, Any]:
        settings = get_settings()
        engine = create_engine(settings.postgres.async_dsn())
        factory = create_session_factory(engine)
        clickhouse = clickhouse_client()
        catalog = HttpServiceClient("catalog")
        service_token = encode_token("us_system", settings.app.auth_secret)
        try:
            updated = await recalculate_quality_scores(
                reports,
                catalog,
                auth_header={"Authorization": f"Bearer {service_token}"},
            )
            async with factory() as session:
                published = await refresh_runtime_metrics(session, clickhouse)
        finally:
            await catalog.aclose()
            await clickhouse.close()
            await engine.dispose()
        return {
            "updated": len(updated),
            "datasets": updated,
            "lag_seconds": published.get(READINGS_TOPIC),
        }

    return asyncio.run(_run())


def _is_fresh(**_context: Any) -> bool:
    """Сенсор свежести: отчёт должен быть за сегодня."""
    day = _latest_report_day()
    return day == datetime.now(UTC).date().isoformat()


with DAG(
    dag_id="refresh_quality",
    description="Пересчёт рейтинга качества датасетов из отчёта",
    schedule="@hourly",
    start_date=DEFAULT_START,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["quality", "us2"],
) as dag:
    freshness = PythonSensor(
        task_id="quality_freshness",
        python_callable=_is_fresh,
        mode="reschedule",
        poke_interval=60,
        timeout=1800,
    )
    recalculate = PythonOperator(task_id="recalculate", python_callable=_recalculate)

    freshness >> recalculate


__all__ = ["dag"]
