"""Идемпотентная запись слоёв: детерминированные ключи и upsert (T129).

Повторный прогон не создаёт дублей: silver-партиции адресуются ключом
``silver/{dataset_id}/{dt}``, а строки схлопываются по ``reading_id`` с
победой последней версии (upsert, FR-024, SC-005).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

SILVER_PREFIX = "silver"


def silver_key(dataset_id: str, dt: date) -> str:
    """Детерминированный ключ партиции silver."""
    return f"{SILVER_PREFIX}/{dataset_id}/{dt.isoformat()}"


def dedupe_by_key(frame: pd.DataFrame, key: str = "reading_id") -> pd.DataFrame:
    """Схлопнуть строки по ключу, оставив последнюю версию (upsert)."""
    if frame.empty or key not in frame.columns:
        return frame
    return frame.drop_duplicates(subset=[key], keep="last").reset_index(drop=True)


def merge_frames(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    key: str = "reading_id",
) -> pd.DataFrame:
    """Слить существующую партицию с новой, устранив дубли по ключу."""
    if existing.empty:
        return dedupe_by_key(incoming, key)
    if incoming.empty:
        return dedupe_by_key(existing, key)
    combined = pd.concat([existing, incoming], ignore_index=True)
    return dedupe_by_key(combined, key)


def row_fingerprint(row: dict[str, Any]) -> str:
    """Детерминированный отпечаток строки для аудита идемпотентности."""
    parts = [str(row.get(column, "")) for column in sorted(row)]
    return "|".join(parts)


__all__ = [
    "SILVER_PREFIX",
    "dedupe_by_key",
    "merge_frames",
    "row_fingerprint",
    "silver_key",
]
