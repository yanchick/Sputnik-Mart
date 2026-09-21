"""Prometheus-метрики: HTTP, лаг консьюмеров, свежесть и качество данных."""

from __future__ import annotations

from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REQUEST_COUNT: Final[Counter] = Counter(
    "sputnik_http_requests_total",
    "Число HTTP-запросов",
    ["service", "method", "route", "status"],
)
REQUEST_LATENCY: Final[Histogram] = Histogram(
    "sputnik_http_request_duration_seconds",
    "Длительность HTTP-запросов",
    ["service", "method", "route"],
)
CONSUMER_LAG: Final[Gauge] = Gauge(
    "sputnik_consumer_lag",
    "Лаг консьюмера по топику и партиции",
    ["topic", "partition"],
)
DATA_FRESHNESS: Final[Gauge] = Gauge(
    "sputnik_data_freshness_seconds",
    "Свежесть данных датасета в секундах",
    ["dataset"],
)
QUALITY_SCORE: Final[Gauge] = Gauge(
    "sputnik_quality_score",
    "Рейтинг качества датасета [0..1]",
    ["dataset"],
)
QUALITY_DEGRADATION: Final[Gauge] = Gauge(
    "sputnik_quality_degradation_ratio",
    "Относительная деградация качества датасета [0..1]",
    ["dataset"],
)


def observe_request(service: str, method: str, route: str, status: int, seconds: float) -> None:
    """Зафиксировать факт и длительность HTTP-запроса."""
    REQUEST_COUNT.labels(service=service, method=method, route=route, status=str(status)).inc()
    REQUEST_LATENCY.labels(service=service, method=method, route=route).observe(seconds)


def set_consumer_lag(topic: str, partition: int, lag: float) -> None:
    """Установить текущий лаг консьюмера."""
    CONSUMER_LAG.labels(topic=topic, partition=str(partition)).set(lag)


def set_data_freshness(dataset: str, seconds: float) -> None:
    """Установить свежесть данных датасета (секунды с последнего обновления)."""
    DATA_FRESHNESS.labels(dataset=dataset).set(max(seconds, 0.0))


def set_quality_score(dataset: str, score: float) -> None:
    """Установить рейтинг качества датасета, зажав его в ``[0,1]``."""
    QUALITY_SCORE.labels(dataset=dataset).set(min(max(score, 0.0), 1.0))


def set_quality_degradation(dataset: str, ratio: float) -> None:
    """Установить относительную деградацию качества, зажав её в ``[0,1]``."""
    QUALITY_DEGRADATION.labels(dataset=dataset).set(min(max(ratio, 0.0), 1.0))


def render_metrics() -> bytes:
    """Сериализовать реестр метрик в формате Prometheus."""
    return generate_latest()


__all__ = [
    "CONSUMER_LAG",
    "CONTENT_TYPE_LATEST",
    "DATA_FRESHNESS",
    "QUALITY_DEGRADATION",
    "QUALITY_SCORE",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "observe_request",
    "render_metrics",
    "set_consumer_lag",
    "set_data_freshness",
    "set_quality_degradation",
    "set_quality_score",
]
