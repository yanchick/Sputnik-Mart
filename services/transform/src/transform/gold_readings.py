"""Silver → gold: ``fact_readings``, часовые агрегаты и прогноз (T118/T119).

Загрузка идемпотентна: повторный прогон за ту же дату не создаёт дублей —
уже существующие ``reading_id`` пропускаются. ``mv_readings_hourly``
наполняется материализованным представлением при вставке фактов.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

FACT_COLUMNS: tuple[str, ...] = (
    "reading_id",
    "station_id",
    "provider_id",
    "metric",
    "value",
    "unit",
    "lat",
    "lon",
    "measured_at",
    "received_at",
    "dt",
)
HOURLY_COLUMNS: tuple[str, ...] = (
    "station_id",
    "metric",
    "hour",
    "readings",
    "avg_value",
    "min_value",
    "max_value",
)
FORECAST_COLUMNS: tuple[str, ...] = (
    "station_id",
    "metric",
    "hour",
    "forecast_value",
)


def build_fact_rows(frame: pd.DataFrame) -> list[list[Any]]:
    """Преобразовать silver-фрейм в строки ``fact_readings``."""
    if frame.empty:
        return []
    rows: list[list[Any]] = []
    for record in frame.to_dict(orient="records"):
        measured = _as_utc(record.get("measured_at"))
        received = _as_utc(record.get("received_at"))
        if measured is None:
            continue
        rows.append(
            [
                str(record.get("reading_id", "")),
                str(record.get("station_id", "")),
                str(record.get("provider_id", "")),
                str(record.get("metric", "")),
                float(record.get("value", 0.0)),
                str(record.get("unit", "")),
                _as_float(record.get("lat")),
                _as_float(record.get("lon")),
                measured,
                received or measured,
                measured.date(),
            ]
        )
    return rows


def hourly_aggregates(frame: pd.DataFrame) -> pd.DataFrame:
    """Часовые агрегаты по станции и метрике (наполнение ``mv_readings_hourly``)."""
    columns = list(HOURLY_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    working = frame.copy()
    working["measured_at"] = pd.to_datetime(working["measured_at"], utc=True, errors="coerce")
    working = working.dropna(subset=["measured_at"])
    if working.empty:
        return pd.DataFrame(columns=columns)
    working["hour"] = working["measured_at"].dt.floor("h")
    grouped = (
        working.groupby(["station_id", "metric", "hour"], as_index=False)
        .agg(
            readings=("reading_id", "count"),
            avg_value=("value", "mean"),
            min_value=("value", "min"),
            max_value=("value", "max"),
        )
        .sort_values(["station_id", "metric", "hour"])
    )
    return grouped[columns]


def forecast_series(frame: pd.DataFrame, *, horizon_hours: int = 3) -> list[dict[str, Any]]:
    """Детерминированный прогноз часового ряда (тренд + суточная сезонность)."""
    aggregates = hourly_aggregates(frame)
    if aggregates.empty:
        return []
    horizon = max(1, horizon_hours)
    predictions: list[dict[str, Any]] = []
    for (station, metric), group in aggregates.groupby(["station_id", "metric"]):
        ordered = group.sort_values("hour")
        values = ordered["avg_value"].to_numpy(dtype=float)
        if values.size < 3:
            continue
        steps = np.arange(values.size, dtype=float)
        design = np.column_stack(
            [
                np.ones(values.size),
                steps,
                np.sin(2 * np.pi * steps / 24.0),
                np.cos(2 * np.pi * steps / 24.0),
            ]
        )
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
        last_hour = pd.Timestamp(ordered["hour"].iloc[-1])
        for offset in range(1, horizon + 1):
            position = float(values.size - 1 + offset)
            features = np.array(
                [
                    1.0,
                    position,
                    np.sin(2 * np.pi * position / 24.0),
                    np.cos(2 * np.pi * position / 24.0),
                ]
            )
            predicted = float(features @ coefficients)
            predictions.append(
                {
                    "station_id": str(station),
                    "metric": str(metric),
                    "hour": (last_hour + pd.Timedelta(hours=offset)).to_pydatetime(),
                    "forecast_value": round(predicted, 6),
                }
            )
    return predictions


async def existing_reading_ids(client: Any, dt: Any) -> set[str]:
    """Вернуть уже загруженные ``reading_id`` за дату (идемпотентность)."""
    result = await client.execute(
        "SELECT reading_id FROM fact_readings WHERE dt = {dt:Date}", {"dt": dt}
    )
    return {str(row[0]) for row in result.result_rows}


async def load_gold_readings(client: Any, rows: Sequence[Sequence[Any]], dt: Any) -> int:
    """Идемпотентно загрузить факты чтений; вернуть число новых строк.

    Дедупликация идёт по дню самого факта (``dt`` = ``toDate(measured_at)``
    из строки), а не по дате прогона: иначе при расхождении даты измерения и
    даты обработки повторный запуск вставлял бы дубли (SC-005). Параметр
    ``dt`` используется как запасной день, если строка его не задаёт.
    """
    if not rows:
        return 0
    rows_by_day: dict[Any, list[list[Any]]] = {}
    for row in rows:
        day = row[10] if len(row) > 10 and row[10] is not None else dt
        rows_by_day.setdefault(day, []).append(list(row))

    loaded = 0
    for day, day_rows in rows_by_day.items():
        existing = await existing_reading_ids(client, day)
        fresh = [row for row in day_rows if str(row[0]) not in existing]
        if not fresh:
            continue
        await client.insert("fact_readings", fresh, column_names=list(FACT_COLUMNS))
        loaded += len(fresh)
    return loaded


def build_forecast_rows(records: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """Преобразовать записи ``forecasts.ndjson`` в строки таблицы ``forecasts``."""
    rows: list[list[Any]] = []
    for record in records:
        station_id = str(record.get("station_id") or "")
        metric = str(record.get("metric") or "")
        hour = _as_utc(record.get("hour"))
        if not station_id or not metric or hour is None:
            continue
        rows.append([station_id, metric, hour, float(record.get("forecast_value", 0.0) or 0.0)])
    return rows


async def load_forecasts(client: Any, rows: Sequence[Sequence[Any]]) -> int:
    """Идемпотентно загрузить прогноз по ключу ``(station_id, metric, hour)``.

    Перед вставкой прежние строки по тем же ключам удаляются, поэтому повторная
    загрузка того же прогноза не создаёт дублей (FR-019).
    """
    if not rows:
        return 0
    for row in rows:
        station_id, metric, hour = str(row[0]), str(row[1]), _as_utc(row[2])
        if hour is None:
            continue
        await client.command(
            "ALTER TABLE forecasts DELETE WHERE "
            f"station_id = '{_escape(station_id)}' AND metric = '{_escape(metric)}' "
            f"AND hour = toDateTime('{_format_datetime(hour)}') SETTINGS mutations_sync = 1"
        )
    await client.insert(
        "forecasts", [list(row) for row in rows], column_names=list(FORECAST_COLUMNS)
    )
    return len(rows)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _escape(value: str) -> str:
    return value.replace("'", "''")


def _as_utc(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    converted: datetime = timestamp.tz_convert(UTC).to_pydatetime()
    return converted


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if np.isnan(number) else number


__all__ = [
    "FACT_COLUMNS",
    "FORECAST_COLUMNS",
    "HOURLY_COLUMNS",
    "build_fact_rows",
    "build_forecast_rows",
    "existing_reading_ids",
    "forecast_series",
    "hourly_aggregates",
    "load_forecasts",
    "load_gold_readings",
]
