"""Публикация метрик лага и свежести из реальных источников (T166, FR-026).

Раньше ``publish_consumer_lag``/``publish_data_freshness`` не имели вызовов в
рантайме, поэтому ``/metrics`` отдавал значения по умолчанию. Здесь метрики
вычисляются из фактических данных: лаг — от последнего ``received_at`` в
``fact_readings`` до текущего момента, свежесть — от ``last_updated_at``
датасета каталога. Функции принимают сессию/клиент, поэтому проверяются
unit-тестами без реальных Postgres/ClickHouse.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import ContentTopic
from observability import get_logger

from .metrics import publish_consumer_lag, publish_data_freshness

_log = get_logger(__name__)

READINGS_TOPIC: str = ContentTopic.READINGS.value
READINGS_PARTITION = 0


async def latest_fact_received_at(clickhouse: Any) -> datetime | None:
    """Максимальный ``received_at`` фактов чтений или ``None`` (пустая витрина)."""
    result = await clickhouse.execute("SELECT max(received_at) FROM fact_readings")
    rows = getattr(result, "result_rows", None) or []
    if not rows:
        return None
    value = rows[0][0]
    return value if isinstance(value, datetime) else None


async def dataset_last_updated(session: AsyncSession) -> list[tuple[str, datetime | None]]:
    """Пары ``(dataset_id, last_updated_at)`` из каталога."""
    result = await session.execute(
        text("SELECT dataset_id, last_updated_at FROM catalog.datasets ORDER BY dataset_id")
    )
    return [(str(row["dataset_id"]), row["last_updated_at"]) for row in result.mappings()]


async def refresh_runtime_metrics(
    session: AsyncSession,
    clickhouse: Any,
    *,
    now: datetime | None = None,
) -> dict[str, float]:
    """Опубликовать лаг консьюмера и свежесть датасетов; вернуть значения."""
    reference = now or datetime.now(UTC)
    published: dict[str, float] = {}
    published[READINGS_TOPIC] = publish_consumer_lag(
        READINGS_TOPIC,
        READINGS_PARTITION,
        await latest_fact_received_at(clickhouse),
        now=reference,
    )
    for dataset_id, updated_at in await dataset_last_updated(session):
        published[dataset_id] = publish_data_freshness(dataset_id, updated_at, now=reference)
    _log.info(
        "runtime_metrics_published", datasets=len(published) - 1, lag=published[READINGS_TOPIC]
    )
    return published


__all__ = [
    "READINGS_PARTITION",
    "READINGS_TOPIC",
    "dataset_last_updated",
    "latest_fact_received_at",
    "refresh_runtime_metrics",
]
