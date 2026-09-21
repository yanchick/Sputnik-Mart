"""Метрики лага консьюмеров, свежести витрины и деградации (T166, FR-026).

Значения публикуются в prometheus-client и служат источником для Grafana-дашборда
``lag_freshness`` и алерта ``degradation``. Чистые функции отделены от публикации,
поэтому расчёт проверяется unit-тестами без реестра метрик.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from observability import (
    set_consumer_lag,
    set_data_freshness,
    set_quality_degradation,
    set_quality_score,
)

DEFAULT_DEGRADATION_THRESHOLD = 0.15
DEFAULT_QUALITY_BASELINE = 0.9


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def consumer_lag_seconds(latest_event_at: datetime | None, *, now: datetime | None = None) -> float:
    """Лаг консьюмера в секундах от момента последнего события до ``now``."""
    if latest_event_at is None:
        return 0.0
    reference = _as_utc(now) if now is not None else datetime.now(UTC)
    return max(0.0, (reference - _as_utc(latest_event_at)).total_seconds())


def data_freshness_seconds(
    last_updated_at: datetime | None, *, now: datetime | None = None
) -> float:
    """Свежесть витрины: секунды с момента последнего обновления."""
    return consumer_lag_seconds(last_updated_at, now=now)


def quality_degradation_ratio(score: float, baseline: float = DEFAULT_QUALITY_BASELINE) -> float:
    """Относительная деградация качества ``(baseline - score) / baseline``."""
    if baseline <= 0.0:
        return 0.0
    return min(max((baseline - score) / baseline, 0.0), 1.0)


def publish_consumer_lag(
    topic: str,
    partition: int,
    latest_event_at: datetime | None,
    *,
    now: datetime | None = None,
) -> float:
    """Опубликовать лаг консьюмера и вернуть вычисленное значение."""
    lag = consumer_lag_seconds(latest_event_at, now=now)
    set_consumer_lag(topic, partition, lag)
    return lag


def publish_data_freshness(
    dataset: str, last_updated_at: datetime | None, *, now: datetime | None = None
) -> float:
    """Опубликовать свежесть витрины датасета и вернуть значение."""
    freshness = data_freshness_seconds(last_updated_at, now=now)
    set_data_freshness(dataset, freshness)
    return freshness


def publish_quality(
    dataset: str,
    score: float,
    *,
    baseline: float = DEFAULT_QUALITY_BASELINE,
) -> float:
    """Опубликовать качество и его деградацию; вернуть относительную деградацию."""
    degradation = quality_degradation_ratio(score, baseline)
    set_quality_score(dataset, score)
    set_quality_degradation(dataset, degradation)
    return degradation


@dataclass(frozen=True)
class DegradationAlert:
    """Сигнал деградации датасета для Grafana-алерта и Quality-dashboard."""

    dataset: str
    quality_score: float
    baseline: float
    degradation: float
    threshold: float
    active: bool


def evaluate_degradation_alerts(
    rows: Iterable[Mapping[str, Any]],
    *,
    baseline: float = DEFAULT_QUALITY_BASELINE,
    threshold: float = DEFAULT_DEGRADATION_THRESHOLD,
) -> list[DegradationAlert]:
    """Оценить деградацию по срезу качества; ``active`` — превышение порога."""
    alerts: list[DegradationAlert] = []
    for row in rows:
        score = float(row.get("quality_score", row.get("qualityScore", 0.0)))
        degradation = quality_degradation_ratio(score, baseline)
        alerts.append(
            DegradationAlert(
                dataset=str(row.get("dataset_id", row.get("datasetId", ""))),
                quality_score=score,
                baseline=baseline,
                degradation=degradation,
                threshold=threshold,
                active=degradation > threshold,
            )
        )
    return alerts


__all__ = [
    "DEFAULT_DEGRADATION_THRESHOLD",
    "DEFAULT_QUALITY_BASELINE",
    "DegradationAlert",
    "consumer_lag_seconds",
    "data_freshness_seconds",
    "evaluate_degradation_alerts",
    "publish_consumer_lag",
    "publish_data_freshness",
    "publish_quality",
    "quality_degradation_ratio",
]
