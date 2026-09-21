"""Оркестрация silver → gold: факты, качество, прогноз, тональность (T118)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from .gold_quality import build_quality_rows, load_quality_mart
from .gold_readings import build_fact_rows, forecast_series, load_gold_readings
from .gold_sales import build_sales_rows, load_sales_mart
from .gold_sentiment import build_sentiment_rows, load_sentiment_mart


async def transform_batch(
    client: Any,
    frame: pd.DataFrame,
    reports: Mapping[str, Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
    *,
    dt: Any,
    orders: Sequence[Mapping[str, Any]] = (),
    downloads: Sequence[Mapping[str, Any]] = (),
    subscriptions: Sequence[Mapping[str, Any]] = (),
    clicks: Sequence[Mapping[str, Any]] = (),
) -> dict[str, int]:
    """Загрузить gold-витрины и вернуть число загруженных строк по витринам."""
    facts = await load_gold_readings(client, build_fact_rows(frame), dt)
    quality = await load_quality_mart(client, build_quality_rows(reports))
    sentiment = await load_sentiment_mart(client, build_sentiment_rows(reviews))
    sales = await load_sales_mart(
        client,
        build_sales_rows(orders, downloads, subscriptions=subscriptions, clicks=clicks),
    )
    return {
        "fact_readings": facts,
        "mart_quality_daily": quality,
        "mart_sentiment_daily": sentiment,
        "mart_sales_daily": sales,
    }


def build_forecasts(frame: pd.DataFrame, *, horizon_hours: int = 3) -> list[dict[str, Any]]:
    """Построить прогноз часовых рядов (чистая функция, T105)."""
    return forecast_series(frame, horizon_hours=horizon_hours)


__all__ = ["build_forecasts", "transform_batch"]
