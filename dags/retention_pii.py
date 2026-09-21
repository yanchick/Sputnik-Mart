"""DAG ``retention_pii``: ежедневное удаление просроченного PII (T171, FR-037, SC-013).

Retention-job запускается по расписанию ``@daily`` и идемпотентен: ``DELETE``
удаляет только PII покупателей старше ``PII_RETENTION_MONTHS`` (по умолчанию
12), поэтому повторный прогон за день не меняет данные. Модуль импортируется и
без установленного Airflow: job доступен для unit-тестов, а DAG собирается
только при наличии Airflow.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from identity.retention import run_retention_job

try:  # pragma: no cover - ветка зависит от наличия Airflow в окружении
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    AIRFLOW_AVAILABLE = True
except ImportError:  # pragma: no cover
    DAG = None  # type: ignore[assignment,misc]
    PythonOperator = None  # type: ignore[assignment,misc]
    AIRFLOW_AVAILABLE = False


async def execute_retention(session_factory: Callable[[], Any], *, months: int) -> int:
    """Открыть сессию, выполнить retention и закоммитить; вернуть число записей."""
    async with session_factory() as session:
        deleted = await run_retention_job(session, months=months)
        await session.commit()
    return deleted


def run_retention(**_context: Any) -> dict[str, int]:
    """Задача DAG: удалить просроченный PII за срок из настроек."""
    from config import get_settings
    from db.postgres import create_engine, create_session_factory

    settings = get_settings()
    engine = create_engine(settings.postgres.async_dsn())
    factory = create_session_factory(engine)
    try:
        deleted = asyncio.run(execute_retention(factory, months=settings.app.pii_retention_months))
    finally:
        asyncio.run(engine.dispose())
    return {"deleted": deleted}


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
        dag_id="retention_pii",
        description="Ежедневное удаление PII покупателей по сроку хранения",
        schedule="@daily",
        start_date=datetime(2026, 9, 1, tzinfo=UTC),
        catchup=False,
        default_args=DEFAULT_ARGS,
        tags=["identity", "privacy", "us4"],
    ) as dag:
        delete_expired = PythonOperator(
            task_id="delete_expired_pii",
            python_callable=run_retention,
        )


__all__ = ["AIRFLOW_AVAILABLE", "execute_retention", "run_retention"]
