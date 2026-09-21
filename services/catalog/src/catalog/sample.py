"""Детерминированная отдача образца датасета в ``CSV|JSON|PARQUET`` (T076)."""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from contracts import FileFormat, SchemaFieldType

from .repository import Dataset, DatasetField

SAMPLE_ROWS = 5
_STRING_VALUES = ["north", "south", "east", "west", "center"]
_MEDIA_TYPES = {
    FileFormat.CSV: "text/csv",
    FileFormat.JSON: "application/json",
    FileFormat.PARQUET: "application/octet-stream",
}


def _value_for(field: DatasetField, index: int, generator: random.Random) -> Any:
    field_type = SchemaFieldType(field.type)
    if field_type is SchemaFieldType.INT:
        return generator.randint(0, 1000)
    if field_type is SchemaFieldType.DOUBLE:
        return round(generator.uniform(0.0, 100.0), 3)
    if field_type is SchemaFieldType.BOOLEAN:
        return bool(index % 2)
    if field_type is SchemaFieldType.DATETIME:
        return (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)).isoformat()
    if field_type is SchemaFieldType.GEO:
        return {
            "lat": round(59.9 + generator.random(), 5),
            "lon": round(30.3 + generator.random(), 5),
        }
    return _STRING_VALUES[index % len(_STRING_VALUES)]


def build_rows(dataset: Dataset, fields: list[DatasetField]) -> list[dict[str, Any]]:
    """Построить детерминированные строки образца по схеме полей."""
    generator = random.Random(dataset.dataset_id)
    rows: list[dict[str, Any]] = []
    for index in range(SAMPLE_ROWS):
        row: dict[str, Any] = {"readingId": f"rd_{dataset.dataset_id}_{index}"}
        for field in fields:
            row[field.name] = _value_for(field, index, generator)
        rows.append(row)
    return rows


def render_sample(
    dataset: Dataset, fields: list[DatasetField], fmt: FileFormat
) -> tuple[bytes, str]:
    """Отрендерить образец в выбранном формате и вернуть ``(bytes, media_type)``."""
    rows = build_rows(dataset, fields)
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
        return buffer.getvalue().encode("utf-8"), _MEDIA_TYPES[fmt]
    if fmt is FileFormat.JSON:
        return json.dumps(rows, ensure_ascii=False).encode("utf-8"), _MEDIA_TYPES[fmt]
    table = pa.Table.from_pylist(rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes(), _MEDIA_TYPES[fmt]


__all__ = ["SAMPLE_ROWS", "build_rows", "render_sample"]
