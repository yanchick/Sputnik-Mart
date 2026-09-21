"""Партнёрские выгрузки через те же слои и проверки (T110, FR-033).

CSV поставщика ``lake/partner/{provider}/{dt}.csv`` приводится к конверту
чтения; далее запись идёт через bronze → silver и ту же валидацию, что и
потоковые данные. Несоответствие схеме отбраковывается, а не попадает в
аналитику.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

REQUIRED_PARTNER_COLUMNS = ("stationId", "metric", "value", "measuredAt")


def parse_partner_csv(
    content: str,
    provider_id: str,
    *,
    received_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Разобрать CSV поставщика в список конвертов чтений.

    Пустой файл даёт пустой список без ошибки (FR-032). Строки с недостающими
    обязательными колонками пропускаются и не попадают в silver.
    """
    if not content.strip():
        return []
    received = received_at or datetime.now(UTC)
    reader = csv.DictReader(io.StringIO(content))
    fieldnames = reader.fieldnames or []
    if not set(REQUIRED_PARTNER_COLUMNS).issubset(set(fieldnames)):
        return []

    readings: list[dict[str, Any]] = []
    for index, row in enumerate(reader):
        value = _to_float(row.get("value"))
        station = row.get("stationId")
        metric = row.get("metric")
        measured_at = row.get("measuredAt")
        if not station or not metric or value is None or not measured_at:
            continue
        readings.append(
            {
                "readingId": f"rd_partner_{provider_id}_{index:05d}",
                "stationId": station,
                "providerId": provider_id,
                "metric": metric,
                "value": value,
                "unit": row.get("unit") or "",
                "geo": _geo(row),
                "measuredAt": measured_at,
                "receivedAt": received.isoformat(),
            }
        )
    return readings


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _geo(row: Mapping[str, Any]) -> dict[str, float] | None:
    lat = _to_float(row.get("lat"))
    lon = _to_float(row.get("lon"))
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


__all__ = ["REQUIRED_PARTNER_COLUMNS", "parse_partner_csv"]
