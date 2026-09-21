"""Выгрузка датасета в ``CSV|JSON|PARQUET`` (T085)."""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from contracts import FileFormat
from observability import USER_ID_HEADER
from observability.masking import sanitize_export_rows
from service_client import ServiceClient

FULL_ROWS = 25
_STRING_VALUES = ["north", "south", "east", "west", "center"]
_EXTENSIONS = {
    FileFormat.CSV: ("csv", "text/csv"),
    FileFormat.JSON: ("json", "application/json"),
    FileFormat.PARQUET: ("parquet", "application/octet-stream"),
}


async def load_fields(
    catalog: ServiceClient, dataset_id: str, user_id: str
) -> list[dict[str, Any]]:
    """Прочитать поля схемы датасета из catalog-сервиса — владельца схемы (M6)."""
    payload = await catalog.get_json(
        f"/api/v1/datasets/{dataset_id}/schema", headers={USER_ID_HEADER: user_id}
    )
    if not isinstance(payload, list):
        return []
    return [dict(field) for field in payload]


def _value_for(field_type: str, index: int, generator: random.Random) -> Any:
    if field_type == "INT":
        return generator.randint(0, 1000)
    if field_type == "DOUBLE":
        return round(generator.uniform(0.0, 100.0), 3)
    if field_type == "BOOLEAN":
        return bool(index % 2)
    if field_type == "DATETIME":
        return (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)).isoformat()
    if field_type == "GEO":
        return {
            "lat": round(59.9 + generator.random(), 5),
            "lon": round(30.3 + generator.random(), 5),
        }
    return _STRING_VALUES[index % len(_STRING_VALUES)]


def build_rows(dataset_id: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Детерминированные строки выгрузки по схеме полей."""
    generator = random.Random(dataset_id)
    rows: list[dict[str, Any]] = []
    for index in range(FULL_ROWS):
        row: dict[str, Any] = {"readingId": f"rd_{dataset_id}_{index}"}
        for field in fields:
            row[str(field["name"])] = _value_for(str(field["type"]), index, generator)
        rows.append(row)
    return rows


def render_content(
    dataset_id: str, fields: list[dict[str, Any]], fmt: FileFormat
) -> tuple[bytes, str, str]:
    """Отрендерить выгрузку и вернуть ``(content, media_type, extension)``.

    Перед сериализацией строки проходят маскирование PII (FR-028, SC-009).
    """
    rows = sanitize_export_rows(build_rows(dataset_id, fields))
    extension, media_type = _EXTENSIONS[fmt]
    if fmt is FileFormat.CSV:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
                    for key, value in row.items()
                }
            )
        return buffer.getvalue().encode("utf-8"), media_type, extension
    if fmt is FileFormat.JSON:
        return json.dumps(rows, ensure_ascii=False).encode("utf-8"), media_type, extension
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows), sink)
    return sink.getvalue().to_pybytes(), media_type, extension


__all__ = ["FULL_ROWS", "build_rows", "load_fields", "render_content"]
