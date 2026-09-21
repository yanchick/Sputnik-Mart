"""Bronze → silver: Pandera-схемы, дедупликация, пропуски и выбросы (T116).

Неконформные записи не попадают в silver: они возвращаются в карантин с
причиной (FR-017, FR-018). Пустой вход даёт пустой валидный silver без
падения прогона (FR-032).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pandera.pandas as pa

from contracts import (
    QUALITY_SCORE_MAX,
    DeadReadingReason,
    Metric,
    dataset_for_metric,
    quality_score_from_rates,
)

#: Ограничение числа искусственно восстановленных точек на одну серию.
MAX_GAPS_PER_GROUP = 500

SILVER_COLUMNS: tuple[str, ...] = (
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
    "dataset_id",
    "dt",
    "is_outlier",
    "is_filled",
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "reading_id",
    "station_id",
    "provider_id",
    "metric",
    "value",
    "unit",
    "measured_at",
)

SILVER_SCHEMA = pa.DataFrameSchema(
    {
        "reading_id": pa.Column(str, nullable=False),
        "station_id": pa.Column(str, nullable=False),
        "provider_id": pa.Column(str, nullable=False),
        "metric": pa.Column(
            str, checks=pa.Check.isin([metric.value for metric in Metric]), nullable=False
        ),
        "value": pa.Column(float, nullable=False),
        "unit": pa.Column(str, nullable=False),
        "lat": pa.Column(float, checks=pa.Check.in_range(-90.0, 90.0), nullable=True),
        "lon": pa.Column(float, checks=pa.Check.in_range(-180.0, 180.0), nullable=True),
        "measured_at": pa.Column(pa.DateTime, nullable=False),
        "received_at": pa.Column(pa.DateTime, nullable=True),
        "dataset_id": pa.Column(str, nullable=False),
    },
    strict=False,
    coerce=True,
)


@dataclass(frozen=True)
class QualityMetrics:
    """Метрики качества одного датасета за прогон."""

    total: int = 0
    missing: int = 0
    duplicates: int = 0
    outliers: int = 0
    gaps: int = 0

    @property
    def missing_rate(self) -> float:
        """Доля пропусков среди входных записей."""
        return self.missing / self.total if self.total else 0.0

    @property
    def dup_rate(self) -> float:
        """Доля дублей среди входных записей."""
        return self.duplicates / self.total if self.total else 0.0

    @property
    def outlier_rate(self) -> float:
        """Доля выбросов среди входных записей."""
        return self.outliers / self.total if self.total else 0.0

    @property
    def gap_rate(self) -> float:
        """Доля восстановленных пропусков ряда среди входных записей."""
        return self.gaps / self.total if self.total else 0.0

    @property
    def anomalies(self) -> int:
        """Суммарное число аномалий (выбросы + пропуски ряда)."""
        return self.outliers + self.gaps

    @property
    def quality_score(self) -> float:
        """Итоговый рейтинг качества ``[0..1]``; пусто — ``1.0`` (FR-032)."""
        if self.total == 0:
            return QUALITY_SCORE_MAX
        return quality_score_from_rates(
            missing_rate=self.missing_rate,
            dup_rate=self.dup_rate,
            outlier_rate=self.outlier_rate,
            gap_rate=self.gap_rate,
        )


@dataclass(frozen=True)
class QuarantinedRow:
    """Неконформная запись с причиной отбраковки."""

    raw: dict[str, Any]
    reason: DeadReadingReason


@dataclass
class CleanBatch:
    """Результат очистки: silver-фрейм, карантин и метрики по датасетам."""

    frame: pd.DataFrame
    quarantine: list[QuarantinedRow] = field(default_factory=list)
    metrics_by_dataset: dict[str, QualityMetrics] = field(default_factory=dict)

    @property
    def metrics(self) -> QualityMetrics:
        """Суммарные метрики по всем датасетам батча."""
        return QualityMetrics(
            total=sum(m.total for m in self.metrics_by_dataset.values()),
            missing=sum(m.missing for m in self.metrics_by_dataset.values()),
            duplicates=sum(m.duplicates for m in self.metrics_by_dataset.values()),
            outliers=sum(m.outliers for m in self.metrics_by_dataset.values()),
            gaps=sum(m.gaps for m in self.metrics_by_dataset.values()),
        )


def _dataset_of(record: Mapping[str, Any]) -> str:
    try:
        return dataset_for_metric(Metric(str(record.get("metric"))))
    except ValueError:
        return "ds_unknown"


def _to_frame(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        geo = record.get("geo") if isinstance(record.get("geo"), Mapping) else {}
        rows.append(
            {
                "reading_id": record.get("readingId"),
                "station_id": record.get("stationId"),
                "provider_id": record.get("providerId"),
                "metric": record.get("metric"),
                "value": record.get("value"),
                "unit": record.get("unit"),
                "lat": (geo or {}).get("lat"),
                "lon": (geo or {}).get("lon"),
                "measured_at": record.get("measuredAt"),
                "received_at": record.get("receivedAt"),
                "dataset_id": _dataset_of(record),
            }
        )
    frame = pd.DataFrame(rows, columns=list(SILVER_COLUMNS[:11]))
    return frame


def _coerce(frame: pd.DataFrame) -> pd.DataFrame:
    coerced = frame.copy()
    coerced["value"] = pd.to_numeric(coerced["value"], errors="coerce")
    coerced["lat"] = pd.to_numeric(coerced["lat"], errors="coerce")
    coerced["lon"] = pd.to_numeric(coerced["lon"], errors="coerce")
    coerced["measured_at"] = pd.to_datetime(coerced["measured_at"], utc=True, errors="coerce")
    coerced["received_at"] = pd.to_datetime(coerced["received_at"], utc=True, errors="coerce")
    coerced["dt"] = coerced["measured_at"].dt.date
    coerced["is_outlier"] = False
    coerced["is_filled"] = False
    return coerced[list(SILVER_COLUMNS)]


def _outlier_flags(group: pd.Series) -> pd.Series:
    if len(group) < 4:
        return pd.Series(False, index=group.index)
    q1 = group.quantile(0.25)
    q3 = group.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return pd.Series(False, index=group.index)
    return (group < q1 - 3 * iqr) | (group > q3 + 3 * iqr)


def _clip_outliers(frame: pd.DataFrame) -> pd.DataFrame:
    clipped = frame.copy()
    keys = ["station_id", "metric"]

    def bounds(group: pd.Series) -> tuple[float, float]:
        q1 = group.quantile(0.25)
        q3 = group.quantile(0.75)
        iqr = q3 - q1
        return q1 - 3 * iqr, q3 + 3 * iqr

    for _, group in clipped.groupby(keys):
        low, high = bounds(group["value"])
        mask = group.index
        clipped.loc[mask, "value"] = group["value"].clip(lower=low, upper=high).to_numpy()
    return clipped


def _fill_gaps(frame: pd.DataFrame, metrics: dict[str, QualityMetrics]) -> pd.DataFrame:
    if frame.empty:
        return frame
    filled_rows: list[pd.Series] = []
    keys = ["station_id", "metric"]
    for (station, metric), group in frame.groupby(keys):
        ordered = group.sort_values("measured_at")
        times = pd.to_datetime(ordered["measured_at"], utc=True)
        deltas = times.diff().dropna()
        if deltas.empty:
            continue
        step = deltas.median()
        if step <= pd.Timedelta(0):
            continue
        existing = set(times)
        full = pd.date_range(times.min(), times.max(), freq=step)
        missing = [point for point in full if point not in existing][:MAX_GAPS_PER_GROUP]
        if not missing:
            continue
        series = ordered.set_index(times)["value"]
        dataset = str(ordered.iloc[0]["dataset_id"])
        current = metrics.get(dataset, QualityMetrics())
        metrics[dataset] = QualityMetrics(
            total=current.total,
            missing=current.missing,
            duplicates=current.duplicates,
            outliers=current.outliers,
            gaps=current.gaps + len(missing),
        )
        for point in missing:
            previous = series.loc[:point]
            value = previous.iloc[-1] if not previous.empty else series.iloc[0]
            row = ordered.iloc[0].copy()
            row["reading_id"] = f"rd_gap_{station}_{metric}_{int(point.timestamp())}"
            row["measured_at"] = point
            row["value"] = value
            row["is_filled"] = True
            row["is_outlier"] = False
            filled_rows.append(row)
    if not filled_rows:
        return frame
    return pd.concat([frame, pd.DataFrame(filled_rows)], ignore_index=True)


def _quarantine_schema_failures(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list[QuarantinedRow]]:
    if frame.empty:
        return frame, []
    try:
        SILVER_SCHEMA.validate(frame, lazy=True)
        return frame, []
    except pa.errors.SchemaErrors as exc:  # pragma: no cover - защитная ветка
        failures = exc.failure_cases
        bad_index = {int(index) for index in failures["index"].dropna().tolist()}
        quarantined = [
            QuarantinedRow(raw=frame.loc[index].to_dict(), reason=DeadReadingReason.SCHEMA_MISMATCH)
            for index in sorted(bad_index)
            if index in frame.index
        ]
        return frame.drop(index=[i for i in bad_index if i in frame.index]), quarantined


def clean_readings(records: Sequence[Any]) -> CleanBatch:
    """Очистить bronze-записи и собрать валидный silver-фрейм.

    Устраняет пропуски, дубли и выбросы, восстанавливает пропуски временного
    ряда и возвращает неконформные записи в карантин.
    """
    valid_records = [record for record in records if isinstance(record, Mapping)]
    if not valid_records:
        return CleanBatch(frame=pd.DataFrame(columns=list(SILVER_COLUMNS)))

    raw = _to_frame(valid_records)
    quarantine: list[QuarantinedRow] = []
    per_dataset: dict[str, QualityMetrics] = {}

    def _bump(dataset: str, field_name: str, amount: int) -> None:
        current = per_dataset.get(dataset, QualityMetrics())
        updated = current
        if field_name == "total":
            updated = QualityMetrics(
                total=current.total + amount,
                missing=current.missing,
                duplicates=current.duplicates,
                outliers=current.outliers,
                gaps=current.gaps,
            )
        per_dataset[dataset] = updated

    for dataset, count in raw["dataset_id"].value_counts().items():
        _bump(str(dataset), "total", int(count))

    raw = _coerce(raw)
    null_mask = raw[list(REQUIRED_COLUMNS)].isna().any(axis=1)
    for _index, row in raw[null_mask].iterrows():
        reason = (
            DeadReadingReason.NULL_VALUE
            if pd.isna(row.get("value")) or pd.isna(row.get("reading_id"))
            else DeadReadingReason.SCHEMA_MISMATCH
        )
        quarantine.append(QuarantinedRow(raw=row.to_dict(), reason=reason))
        current = per_dataset.get(str(row["dataset_id"]), QualityMetrics())
        per_dataset[str(row["dataset_id"])] = QualityMetrics(
            total=current.total,
            missing=current.missing + 1,
            duplicates=current.duplicates,
            outliers=current.outliers,
            gaps=current.gaps,
        )
    frame = raw[~null_mask].copy()

    duplicate_mask = frame.duplicated(subset=["reading_id"], keep="first")
    for _index, row in frame[duplicate_mask].iterrows():
        quarantine.append(QuarantinedRow(raw=row.to_dict(), reason=DeadReadingReason.DUPLICATE))
        current = per_dataset.get(str(row["dataset_id"]), QualityMetrics())
        per_dataset[str(row["dataset_id"])] = QualityMetrics(
            total=current.total,
            missing=current.missing,
            duplicates=current.duplicates + 1,
            outliers=current.outliers,
            gaps=current.gaps,
        )
    frame = frame[~duplicate_mask].reset_index(drop=True)

    if not frame.empty:
        outlier_flags = frame.groupby(["station_id", "metric"])["value"].transform(_outlier_flags)
        frame["is_outlier"] = outlier_flags.fillna(False).astype(bool)
        for dataset, count in frame[frame["is_outlier"]]["dataset_id"].value_counts().items():
            current = per_dataset.get(str(dataset), QualityMetrics())
            per_dataset[str(dataset)] = QualityMetrics(
                total=current.total,
                missing=current.missing,
                duplicates=current.duplicates,
                outliers=current.outliers + int(count),
                gaps=current.gaps,
            )
        frame = _clip_outliers(frame)

    frame = _fill_gaps(frame, per_dataset)
    frame, schema_quarantine = _quarantine_schema_failures(frame)
    quarantine.extend(schema_quarantine)

    return CleanBatch(frame=frame, quarantine=quarantine, metrics_by_dataset=per_dataset)


def reading_to_silver(reading: Mapping[str, Any]) -> dict[str, Any] | None:
    """Преобразовать одно валидное чтение в строку silver (без очистки)."""
    batch = clean_readings([reading])
    if batch.frame.empty:
        return None
    row: dict[str, Any] = batch.frame.iloc[0].to_dict()
    return row


def event_timestamp() -> datetime:
    """Текущее время UTC (для отчётов и партиций)."""
    return datetime.now(UTC)


__all__ = [
    "MAX_GAPS_PER_GROUP",
    "QUALITY_SCORE_MAX",
    "REQUIRED_COLUMNS",
    "SILVER_COLUMNS",
    "SILVER_SCHEMA",
    "CleanBatch",
    "QualityMetrics",
    "QuarantinedRow",
    "clean_readings",
    "event_timestamp",
    "reading_to_silver",
]
