"""Приём чтений датчиков: валидация конверта и простановка ``receivedAt`` (T111).

Инвариант: ``receivedAt`` проставляет **только** шлюз, ``measuredAt`` сохраняется
как переданное источником (FR-011, FR-012, ТЗ §7.2). Неконформные записи
возвращаются как ``DeadReadingPayload`` с причиной и уходят в DLQ.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from contracts import (
    DeadReadingPayload,
    DeadReadingReason,
    GeoPoint,
    Metric,
    SensorReadingPayload,
    metric_bounds,
)


class ReadingInput(BaseModel):
    """Входной конверт чтения без ``receivedAt``: время приёма ставит шлюз."""

    model_config = ConfigDict(extra="ignore")

    readingId: str
    stationId: str
    providerId: str
    metric: Metric
    value: float
    unit: str
    geo: GeoPoint | None = None
    measuredAt: datetime


@dataclass(frozen=True)
class IngestResult:
    """Результат разбора пакета: валидные чтения и битые записи отдельно."""

    accepted: tuple[SensorReadingPayload, ...]
    dead: tuple[DeadReadingPayload, ...]


def _reading_id(raw: Mapping[str, Any]) -> str:
    candidate = raw.get("readingId")
    return str(candidate) if candidate else "rd_unknown"


def _is_out_of_range(raw: Mapping[str, Any]) -> bool:
    try:
        metric = Metric(str(raw.get("metric")))
        value = float(raw["value"])
    except (KeyError, TypeError, ValueError):
        return False
    low, high = metric_bounds(metric)
    return not low <= value <= high


def classify_reading(
    raw: Any,
    *,
    received_at: datetime,
) -> tuple[SensorReadingPayload | None, DeadReadingPayload | None]:
    """Разобрать одно чтение: вернуть либо валидное, либо битое с причиной.

    Причины: ``NULL_VALUE`` — пустое значение; ``OUT_OF_RANGE`` — выход за
    физические границы метрики; ``SCHEMA_MISMATCH`` — всё прочее (FR-016).
    """
    if not isinstance(raw, Mapping):
        return None, DeadReadingPayload(
            readingId=_reading_id({}),
            reason=DeadReadingReason.SCHEMA_MISMATCH,
            raw={"value": raw},
        )

    if "value" in raw and raw.get("value") is None:
        return None, DeadReadingPayload(
            readingId=_reading_id(raw),
            reason=DeadReadingReason.NULL_VALUE,
            raw=dict(raw),
        )

    try:
        parsed = ReadingInput.model_validate(dict(raw))
    except ValidationError:
        reason = (
            DeadReadingReason.OUT_OF_RANGE
            if _is_out_of_range(raw)
            else DeadReadingReason.SCHEMA_MISMATCH
        )
        return None, DeadReadingPayload(
            readingId=_reading_id(raw),
            reason=reason,
            raw=dict(raw),
        )

    low, high = metric_bounds(parsed.metric)
    if not low <= parsed.value <= high:
        return None, DeadReadingPayload(
            readingId=parsed.readingId,
            reason=DeadReadingReason.OUT_OF_RANGE,
            raw=dict(raw),
        )

    accepted = SensorReadingPayload(
        readingId=parsed.readingId,
        stationId=parsed.stationId,
        providerId=parsed.providerId,
        metric=parsed.metric,
        value=parsed.value,
        unit=parsed.unit,
        geo=parsed.geo,
        measuredAt=parsed.measuredAt,
        receivedAt=received_at,
    )
    return accepted, None


class ReadingProcessor:
    """Пакетный разбор входящих чтений с единым ``receivedAt`` на пакет."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def ingest(self, payload: Any) -> IngestResult:
        """Разобрать одно чтение или список; пустой вход даёт пустой результат."""
        received_at = self._clock()
        items: Sequence[Any] = payload if isinstance(payload, list) else [payload]
        accepted: list[SensorReadingPayload] = []
        dead: list[DeadReadingPayload] = []
        for item in items:
            reading, rejected = classify_reading(item, received_at=received_at)
            if reading is not None:
                accepted.append(reading)
            if rejected is not None:
                dead.append(rejected)
        return IngestResult(accepted=tuple(accepted), dead=tuple(dead))


__all__ = [
    "IngestResult",
    "ReadingInput",
    "ReadingProcessor",
    "classify_reading",
]
