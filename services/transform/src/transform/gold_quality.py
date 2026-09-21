"""Silver → gold: витрина ``mart_quality_daily`` (T120).

Загрузка идемпотентна по ключу ``(dt, dataset_id)``: перед вставкой удаляются
прежние строки за дату и датасет (upsert).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

QUALITY_COLUMNS: tuple[str, ...] = (
    "dt",
    "dataset_id",
    "quality_score",
    "missing_rate",
    "dup_rate",
    "outlier_rate",
    "anomalies_cnt",
)


def build_quality_rows(
    reports: Mapping[str, Mapping[str, Any]],
) -> list[list[Any]]:
    """Преобразовать отчёты качества в строки ``mart_quality_daily``."""
    rows: list[list[Any]] = []
    for dataset_id, report in reports.items():
        rows.append(
            [
                _parse_date(report.get("dt")) or datetime.now(UTC).date(),
                str(dataset_id),
                float(report.get("quality_score", 0.0)),
                float(report.get("missing_rate", 0.0)),
                float(report.get("dup_rate", 0.0)),
                float(report.get("outlier_rate", 0.0)),
                int(report.get("anomalies_cnt", 0)),
            ]
        )
    return rows


async def load_quality_mart(client: Any, rows: Sequence[Sequence[Any]]) -> int:
    """Идемпотентно загрузить качество за дни/датасеты; вернуть число строк."""
    if not rows:
        return 0
    keys = sorted({(row[0], row[1]) for row in rows})
    for dt, dataset_id in keys:
        await client.command(
            "ALTER TABLE mart_quality_daily DELETE WHERE "
            f"dt = toDate('{dt}') AND dataset_id = '{_escape(str(dataset_id))}' "
            "SETTINGS mutations_sync = 1"
        )
    await client.insert(
        "mart_quality_daily", [list(row) for row in rows], column_names=list(QUALITY_COLUMNS)
    )
    return len(rows)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _escape(value: str) -> str:
    return value.replace("'", "''")


__all__ = ["QUALITY_COLUMNS", "build_quality_rows", "load_quality_mart"]
