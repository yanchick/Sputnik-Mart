"""DAG ``deliver_subscription``: подписка → свежие чтения (T141, T146, FR-024).

DAG событийный: сенсор ждёт активную подписку, затем выбирает для неё свежие
чтения gold и идемпотентно резервирует их по ``readingId`` в Redis. Подписки в
статусе ``SUB_PAUSED``/``SUB_CANCELLED`` не выбираются вовсе — приостановка
останавливает выборку новых данных (FR-009).

Модуль импортируется и без установленного Airflow: чистые функции отбора
доступны для unit-тестов, а DAG собирается только при наличии Airflow.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts import METRIC_DATASETS, SubscriptionStatus

ACTIVE_STATUS = SubscriptionStatus.SUB_ACTIVE.value
DEFAULT_BATCH_LIMIT = 500

try:  # pragma: no cover - ветка зависит от наличия Airflow в окружении
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    from airflow.sensors.python import PythonSensor

    AIRFLOW_AVAILABLE = True
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]
    PythonSensor = None  # type: ignore[assignment,misc]
    AIRFLOW_AVAILABLE = False


def active_subscriptions(subscriptions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Оставить только ``SUB_ACTIVE``: ``PAUSED``/``CANCELLED`` не выбираются."""
    return [
        subscription
        for subscription in subscriptions
        if str(subscription.get("status")) == ACTIVE_STATUS
    ]


def dataset_for_metric(metric: str) -> str | None:
    """Датасет, которому принадлежит метрика чтения."""
    for known, dataset in METRIC_DATASETS.items():
        if known.value == metric:
            return dataset
    return None


def reading_dataset(reading: Mapping[str, Any]) -> str | None:
    """Определить датасет чтения по явному полю или метрике."""
    explicit = reading.get("datasetId") or reading.get("dataset_id")
    if explicit:
        return str(explicit)
    metric = reading.get("metric")
    return dataset_for_metric(str(metric)) if metric else None


def select_fresh_readings(
    subscriptions: Sequence[Mapping[str, Any]],
    readings: Sequence[Mapping[str, Any]],
    *,
    delivered_ids: set[str] | None = None,
    limit: int | None = DEFAULT_BATCH_LIMIT,
) -> list[dict[str, Any]]:
    """Отобрать свежие чтения активных подписок без уже доставленных.

    Идемпотентность: повторный прогон с тем же ``delivered_ids`` не вернёт
    ни одной строки; дубли внутри пакета также схлопываются.
    """
    delivered = delivered_ids or set()
    selected: list[dict[str, Any]] = []
    seen = set(delivered)
    for subscription in active_subscriptions(subscriptions):
        dataset_id = str(subscription.get("dataset_id") or subscription.get("datasetId") or "")
        if not dataset_id:
            continue
        subscription_id = str(
            subscription.get("subscription_id") or subscription.get("subscriptionId") or ""
        )
        for reading in readings:
            reading_id = str(reading.get("readingId") or reading.get("reading_id") or "")
            if not reading_id or reading_id in seen:
                continue
            if reading_dataset(reading) != dataset_id:
                continue
            seen.add(reading_id)
            selected.append(
                {
                    "subscriptionId": subscription_id,
                    "readingId": reading_id,
                    "datasetId": dataset_id,
                    "value": reading.get("value"),
                    "metric": reading.get("metric"),
                    "measuredAt": reading.get("measuredAt") or reading.get("measured_at"),
                }
            )
            if limit is not None and len(selected) >= limit:
                return selected
    return selected


def _load_active_subscriptions() -> list[dict[str, Any]]:
    """Прочитать активные подписки из Postgres (синхронный вызов в таске)."""
    import asyncio

    from sqlalchemy import text

    from config import get_settings
    from db.postgres import create_engine, create_session_factory

    async def _run() -> list[dict[str, Any]]:
        settings = get_settings()
        engine = create_engine(settings.postgres.async_dsn())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                statement = text("""
                    SELECT subscription_id, user_id, dataset_id, status
                    FROM orders.subscriptions
                    WHERE status = 'SUB_ACTIVE'
                    """)
                result = await session.execute(statement)
                return [dict(row) for row in result.mappings().all()]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _wait_for_subscription(**_context: Any) -> bool:
    """Сенсор: есть хотя бы одна активная подписка, ожидающая доставки."""
    return bool(_load_active_subscriptions())


def _select_and_stage(**_context: Any) -> dict[str, Any]:
    """Выбрать свежие чтения активных подписок и зарезервировать ``readingId``."""
    import asyncio

    from delivery.idempotency import READING_DEDUP_PREFIX

    from config import get_settings
    from db import create_object_store
    from db.redis import IdempotencyStore, create_redis

    subscriptions = _load_active_subscriptions()
    if not subscriptions:
        return {"subscriptions": 0, "selected": 0, "readings": 0}

    async def _run() -> dict[str, Any]:
        settings = get_settings()
        readings = await _read_fresh_readings(settings, subscriptions)
        redis = create_redis(settings.redis.dsn())
        store = IdempotencyStore(redis)
        delivered = {
            reading_id.removeprefix(READING_DEDUP_PREFIX)
            for reading_id in await _reserved_ids(redis, readings)
        }
        selected = select_fresh_readings(subscriptions, readings, delivered_ids=delivered)
        for item in selected:
            await store.reserve(f"{READING_DEDUP_PREFIX}{item['readingId']}", 86_400)
        if selected:
            lake = create_object_store(
                endpoint_url=settings.minio.endpoint,
                aws_access_key_id=settings.minio.access_key,
                aws_secret_access_key=settings.minio.secret_key,
                region_name=settings.minio.region,
            )
            await _write_staging(lake, settings.minio.lake_bucket, selected)
        await redis.aclose()
        return {
            "subscriptions": len(subscriptions),
            "readings": len(readings),
            "selected": len(selected),
        }

    return asyncio.run(_run())


async def _read_fresh_readings(
    settings: Any, subscriptions: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Свежие чтения gold по метрикам датасетов активных подписок."""
    from db.clickhouse import create_client

    datasets = {
        str(subscription.get("dataset_id") or subscription.get("datasetId") or "")
        for subscription in subscriptions
    }
    metrics = [metric.value for metric, dataset in METRIC_DATASETS.items() if dataset in datasets]
    if not metrics:
        return []
    metric_list = ", ".join(f"'{metric}'" for metric in metrics)
    query = f"""
        SELECT reading_id, station_id, metric, value, unit, measured_at, received_at
        FROM fact_readings
        WHERE metric IN ({metric_list})
        ORDER BY received_at DESC
        LIMIT {DEFAULT_BATCH_LIMIT}
        """
    client = create_client(
        host=settings.clickhouse.host,
        port=settings.clickhouse.port,
        username=settings.clickhouse.user,
        password=settings.clickhouse.password,
        database=settings.clickhouse.database,
    )
    try:
        result = await client.execute(query)
    finally:
        await client.close()
    return [
        {
            "readingId": str(row[0]),
            "stationId": str(row[1]),
            "metric": str(row[2]),
            "value": float(row[3]),
            "unit": str(row[4]),
            "measuredAt": row[5],
            "receivedAt": row[6],
        }
        for row in result.result_rows
    ]


async def _reserved_ids(redis: Any, readings: Sequence[Mapping[str, Any]]) -> list[str]:
    """Ключи Redis, уже зарезервированные для чтений (дедупликация)."""
    from delivery.idempotency import READING_DEDUP_PREFIX

    present: list[str] = []
    for reading in readings:
        reading_id = str(reading.get("readingId") or reading.get("reading_id") or "")
        if not reading_id:
            continue
        if await redis.exists(f"idempotency:{READING_DEDUP_PREFIX}{reading_id}"):
            present.append(f"{READING_DEDUP_PREFIX}{reading_id}")
    return present


async def _write_staging(store: Any, bucket: str, selected: Sequence[Mapping[str, Any]]) -> None:
    """Записать отобранные чтения в озеро для доставки по подписке."""
    import json

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        grouped.setdefault(str(item["subscriptionId"]), []).append(dict(item))
    for subscription_id, items in grouped.items():
        body = "\n".join(json.dumps(item, ensure_ascii=False, default=str) for item in items)
        await store.put_bytes(
            bucket,
            f"streams/{subscription_id}/pending.ndjson",
            body.encode("utf-8"),
            "application/x-ndjson",
        )


if AIRFLOW_AVAILABLE:  # pragma: no cover - исполняется только под Airflow
    from datetime import UTC, datetime, timedelta

    from pipeline_io import on_failure

    DEFAULT_ARGS: dict[str, Any] = {
        "owner": "sputnik",
        "retries": 3,
        "retry_delay": timedelta(seconds=30),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=10),
        "on_failure_callback": on_failure,
    }

    with DAG(
        dag_id="deliver_subscription",
        description="Подписка → выборка свежих чтений → доставка (US3)",
        schedule="@continuous",
        start_date=datetime(2026, 9, 1, tzinfo=UTC),
        catchup=False,
        default_args=DEFAULT_ARGS,
        tags=["commerce", "content", "us3"],
    ) as dag:
        wait_for_subscription = PythonSensor(
            task_id="wait_for_subscription",
            python_callable=_wait_for_subscription,
            mode="reschedule",
            poke_interval=30,
            timeout=1800,
        )
        select_fresh = PythonOperator(
            task_id="select_fresh_readings",
            python_callable=_select_and_stage,
        )

        wait_for_subscription >> select_fresh


__all__ = [
    "ACTIVE_STATUS",
    "AIRFLOW_AVAILABLE",
    "active_subscriptions",
    "dataset_for_metric",
    "reading_dataset",
    "select_fresh_readings",
]
