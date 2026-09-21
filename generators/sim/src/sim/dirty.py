"""Генератор ``sim.dirty``: контролируемое загрязнение данных (T124).

Доли пропусков/дублей/выбросов/битых записей задаются явно; результат
детерминирован по ``seed`` (FR-029). Загрязнение применяется к копии, поэтому
исходная выдача не мутируется.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

DEFAULT_SEED = 42


@dataclass(frozen=True)
class DirtyConfig:
    """Доли контролируемого загрязнения ``[0..1]``."""

    missing: float = 0.0
    duplicate: float = 0.0
    outlier: float = 0.0
    broken: float = 0.0

    def __post_init__(self) -> None:
        for name in ("missing", "duplicate", "outlier", "broken"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"доля '{name}' должна быть в [0..1], получено {value}")


def contaminate(
    readings: list[dict[str, Any]],
    *,
    seed: int = DEFAULT_SEED,
    config: DirtyConfig | None = None,
) -> list[dict[str, Any]]:
    """Вернуть загрязнённую копию чтений согласно конфигу."""
    rules = config or DirtyConfig()
    if not readings:
        return []
    generator = random.Random(seed)
    contaminated: list[dict[str, Any]] = []
    for reading in readings:
        record = dict(reading)
        if generator.random() < rules.missing:
            record["value"] = None
        if generator.random() < rules.outlier and record.get("value") is not None:
            record["value"] = float(record["value"]) * generator.choice((1000.0, -1000.0))
        if generator.random() < rules.broken:
            record.pop("stationId", None)
        contaminated.append(record)
        if generator.random() < rules.duplicate:
            contaminated.append(dict(record))
    return contaminated


def contamination_digest(readings: list[dict[str, Any]]) -> str:
    """Детерминированный отпечаток загрязнённой выдачи."""
    import hashlib
    import json

    payload = json.dumps(readings, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_SEED",
    "DirtyConfig",
    "contaminate",
    "contamination_digest",
]
