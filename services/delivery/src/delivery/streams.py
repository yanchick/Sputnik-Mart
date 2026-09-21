"""Источники свежих чтений для живого потока подписки (T142, FR-022).

Реализация по умолчанию читает ``fact_readings`` ClickHouse по метрикам
датасета подписки. В тестах источник подменяется детерминированным
:class:`StaticReadingSource` — FastAPI-эндпоинт не знает разницы.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol

from contracts import METRIC_DATASETS, Metric

DEFAULT_LOOKBACK_MINUTES = 60
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_READING_LIMIT = 200


def metrics_for_dataset(dataset_id: str) -> tuple[Metric, ...]:
    """Вернуть метрики, относящиеся к датасету (обратное к ``METRIC_DATASETS``)."""
    return tuple(metric for metric, dataset in METRIC_DATASETS.items() if dataset == dataset_id)


class ReadingSource(Protocol):
    """Абстракция источника свежих чтений подписки."""

    def stream(self, subscription: Mapping[str, Any]) -> AsyncIterator[Mapping[str, Any]]:
        """Отдавать чтения подписки; в production — бесконечно."""
        ...


class StaticReadingSource:
    """Детерминированный источник из фиксированного списка чтений (тесты)."""

    def __init__(self, readings: Sequence[Mapping[str, Any]]) -> None:
        self._readings = [dict(reading) for reading in readings]

    async def _iterate(self) -> AsyncIterator[Mapping[str, Any]]:
        for reading in self._readings:
            yield reading

    def stream(self, subscription: Mapping[str, Any]) -> AsyncIterator[Mapping[str, Any]]:
        """Вернуть новый проход по фиксированному списку при каждом подключении."""
        return self._iterate()


class ClickHouseReadingSource:
    """Свежие чтения из ``fact_readings`` по метрикам датасета подписки."""

    def __init__(
        self,
        settings: Any,
        *,
        lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        limit: int = DEFAULT_READING_LIMIT,
    ) -> None:
        self._settings = settings
        self._lookback_minutes = lookback_minutes
        self._poll_interval = poll_interval
        self._limit = limit

    def _build_client(self) -> Any:
        from db.clickhouse import create_client

        settings = self._settings.clickhouse
        return create_client(
            host=settings.host,
            port=settings.port,
            username=settings.user,
            password=settings.password,
            database=settings.database,
        )

    async def _stream(self, subscription: Mapping[str, Any]) -> AsyncIterator[Mapping[str, Any]]:
        dataset_id = str(subscription.get("dataset_id") or "")
        metrics = metrics_for_dataset(dataset_id)
        if not metrics:
            return
        metric_list = ", ".join(f"'{metric.value}'" for metric in metrics)
        query = f"""
            SELECT reading_id, station_id, metric, value, unit, measured_at, received_at
            FROM fact_readings
            WHERE metric IN ({metric_list})
              AND received_at >= now() - INTERVAL {int(self._lookback_minutes)} MINUTE
            ORDER BY received_at ASC
            LIMIT {int(self._limit)}
            """
        client = self._build_client()
        try:
            while True:
                result = await client.execute(query)
                for row in result.result_rows:
                    yield {
                        "readingId": str(row[0]),
                        "stationId": str(row[1]),
                        "datasetId": dataset_id,
                        "metric": str(row[2]),
                        "value": float(row[3]),
                        "unit": str(row[4]),
                        "measuredAt": row[5],
                        "receivedAt": row[6],
                    }
                await asyncio.sleep(self._poll_interval)
        finally:
            await client.close()

    def stream(self, subscription: Mapping[str, Any]) -> AsyncIterator[Mapping[str, Any]]:
        """Отдавать поток чтений датасета подписки, опрашивая ClickHouse."""
        return self._stream(subscription)


def create_reading_source(settings: Any) -> ReadingSource:
    """Источник по умолчанию — ClickHouse-выборка свежих чтений."""
    return ClickHouseReadingSource(settings)


__all__ = [
    "DEFAULT_LOOKBACK_MINUTES",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_READING_LIMIT",
    "ClickHouseReadingSource",
    "ReadingSource",
    "StaticReadingSource",
    "create_reading_source",
    "metrics_for_dataset",
]
