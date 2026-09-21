"""Корректная обработка пустого источника без падения прогона (T130, FR-032).

Пустой вход даёт пустой, но валидный silver-фрейм и нулевой отчёт качества;
``quality_score`` при отсутствии данных равен ``1.0`` (нет дефектов).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .validator import QUALITY_SCORE_MAX, SILVER_COLUMNS


def empty_silver_frame() -> pd.DataFrame:
    """Вернуть пустой silver-фрейм с полной схемой колонок."""
    return pd.DataFrame({column: pd.Series(dtype=object) for column in SILVER_COLUMNS})


def empty_quality_report(dataset_id: str, dt: date | None = None) -> dict[str, object]:
    """Вернуть корректный нулевой отчёт о качестве для пустого источника."""
    report_date = dt or date.today()
    return {
        "dt": report_date.isoformat(),
        "dataset_id": dataset_id,
        "quality_score": QUALITY_SCORE_MAX,
        "missing_rate": 0.0,
        "dup_rate": 0.0,
        "outlier_rate": 0.0,
        "gap_rate": 0.0,
        "anomalies_cnt": 0,
        "records": 0,
    }


__all__ = ["empty_quality_report", "empty_silver_frame"]
