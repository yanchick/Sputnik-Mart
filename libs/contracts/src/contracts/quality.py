"""Семантика рейтинга качества датасета ``qualityScore`` (FR-020).

Единая формула используется validation-service (формирует отчёт) и
quality-service (пересчитывает и публикует показатель в каталог), что
гарантирует согласованность каталога и Quality-page.
"""

from __future__ import annotations

QUALITY_SCORE_MIN = 0.0
QUALITY_SCORE_MAX = 1.0
#: Веса дефектов в штрафе: пропуски > дубли > выбросы > пропуски ряда.
MISSING_WEIGHT = 0.5
DUP_WEIGHT = 0.3
OUTLIER_WEIGHT = 0.2
GAP_WEIGHT = 0.1


def quality_score_from_rates(
    *,
    missing_rate: float,
    dup_rate: float,
    outlier_rate: float,
    gap_rate: float = 0.0,
) -> float:
    """Вернуть рейтинг ``[0..1]``: ``1`` — чисто, меньше — деградация."""
    penalty = (
        MISSING_WEIGHT * _clamp_rate(missing_rate)
        + DUP_WEIGHT * _clamp_rate(dup_rate)
        + OUTLIER_WEIGHT * _clamp_rate(outlier_rate)
        + GAP_WEIGHT * _clamp_rate(gap_rate)
    )
    return max(QUALITY_SCORE_MIN, min(QUALITY_SCORE_MAX, 1.0 - penalty))


def _clamp_rate(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


__all__ = [
    "DUP_WEIGHT",
    "GAP_WEIGHT",
    "MISSING_WEIGHT",
    "OUTLIER_WEIGHT",
    "QUALITY_SCORE_MAX",
    "QUALITY_SCORE_MIN",
    "quality_score_from_rates",
]
