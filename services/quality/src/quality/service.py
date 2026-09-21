"""Quality-service: пересчёт и публикация ``qualityScore`` (T121).

Показатель согласован с отчётом validation и Quality-page: формула берётся из
общего контракта ``quality_score_from_rates`` (FR-020). Обновление каталога
идемпотентно (upsert по ``dataset_id``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import quality_score_from_rates
from observability import get_logger
from service_client import ServiceClient

from .metrics import publish_quality

_log = get_logger(__name__)


@dataclass(frozen=True)
class QualitySnapshot:
    """Срез качества датасета для Quality-page."""

    dataset_id: str
    name: str
    quality_score: float
    missing_rate: float
    dup_rate: float
    outlier_rate: float
    anomalies_cnt: int
    dt: date | None = None


def quality_score_from_report(report: Mapping[str, Any]) -> float:
    """Извлечь ``qualityScore`` из отчёта, при отсутствии — пересчитать."""
    if "quality_score" in report:
        return _clamp(float(report["quality_score"]))
    return quality_score_from_rates(
        missing_rate=float(report.get("missing_rate", 0.0)),
        dup_rate=float(report.get("dup_rate", 0.0)),
        outlier_rate=float(report.get("outlier_rate", 0.0)),
        gap_rate=float(report.get("gap_rate", 0.0)),
    )


async def recalculate_quality_scores(
    reports: Mapping[str, Mapping[str, Any]],
    catalog: ServiceClient,
    *,
    auth_header: Mapping[str, str] | None = None,
) -> list[str]:
    """Пересчитать ``quality_score`` через catalog-сервис — владельца (M6).

    Каталог обновляется единственным внутренним эндпоинтом
    ``POST /datasets/quality-scores``; запись в чужие таблицы отсюда убрана.
    """
    if not reports:
        return []
    scores = {
        dataset_id: quality_score_from_report(report) for dataset_id, report in reports.items()
    }
    payload = await catalog.post_json(
        "/api/v1/datasets/quality-scores",
        json={"scores": scores},
        headers=dict(auth_header or {}),
    )
    updated = (
        [str(item) for item in payload.get("updated", [])] if isinstance(payload, Mapping) else []
    )
    for dataset_id, score in scores.items():
        publish_quality(dataset_id, score)
    _log.info("quality_recalculated", datasets=len(updated))
    return updated


async def list_quality_snapshots(session: AsyncSession) -> list[QualitySnapshot]:
    """Вернуть срез качества всех датасетов каталога."""
    result = await session.execute(
        text(
            "SELECT dataset_id, name, quality_score, last_updated_at "
            "FROM catalog.datasets ORDER BY dataset_id"
        )
    )
    snapshots: list[QualitySnapshot] = []
    for row in result.mappings():
        score = float(row["quality_score"])
        snapshots.append(
            QualitySnapshot(
                dataset_id=str(row["dataset_id"]),
                name=str(row["name"]),
                quality_score=score,
                missing_rate=0.0,
                dup_rate=0.0,
                outlier_rate=0.0,
                anomalies_cnt=0,
                dt=_as_date(row["last_updated_at"]),
            )
        )
    return snapshots


async def get_quality_snapshot(session: AsyncSession, dataset_id: str) -> QualitySnapshot | None:
    """Вернуть срез качества одного датасета или ``None``."""
    result = await session.execute(
        text(
            "SELECT dataset_id, name, quality_score, last_updated_at "
            "FROM catalog.datasets WHERE dataset_id = :dataset_id"
        ),
        {"dataset_id": dataset_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return QualitySnapshot(
        dataset_id=str(row["dataset_id"]),
        name=str(row["name"]),
        quality_score=float(row["quality_score"]),
        missing_rate=0.0,
        dup_rate=0.0,
        outlier_rate=0.0,
        anomalies_cnt=0,
        dt=_as_date(row["last_updated_at"]),
    )


def merge_report(snapshot: QualitySnapshot, report: Mapping[str, Any] | None) -> QualitySnapshot:
    """Дополнить срез показателями отчёта (пропуски/дубли/выбросы/аномалии)."""
    if not report:
        return snapshot
    return QualitySnapshot(
        dataset_id=snapshot.dataset_id,
        name=snapshot.name,
        quality_score=quality_score_from_report(report),
        missing_rate=float(report.get("missing_rate", 0.0)),
        dup_rate=float(report.get("dup_rate", 0.0)),
        outlier_rate=float(report.get("outlier_rate", 0.0)),
        anomalies_cnt=int(report.get("anomalies_cnt", 0)),
        dt=snapshot.dt,
    )


def snapshot_payload(snapshot: QualitySnapshot) -> dict[str, Any]:
    """Сериализовать срез в camelCase-контракт Quality-page (FR-021).

    Единый формат для списочного и точечного ответов: ключи совпадают с
    колонками Panel-страницы (``datasetId``, ``qualityScore`` и т.д.).
    """
    return {
        "datasetId": snapshot.dataset_id,
        "name": snapshot.name,
        "qualityScore": snapshot.quality_score,
        "missingRate": snapshot.missing_rate,
        "dupRate": snapshot.dup_rate,
        "outlierRate": snapshot.outlier_rate,
        "anomaliesCnt": snapshot.anomalies_cnt,
        "dt": snapshot.dt.isoformat() if snapshot.dt is not None else None,
    }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


__all__ = [
    "QualitySnapshot",
    "get_quality_snapshot",
    "list_quality_snapshots",
    "merge_report",
    "quality_score_from_report",
    "recalculate_quality_scores",
    "snapshot_payload",
]
