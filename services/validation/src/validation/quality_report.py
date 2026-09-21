"""Отчёт о качестве bronze → silver (T117).

Метрики ``missing/dup/outlier/anomaly`` формируются Pandera-очисткой, а
Great Expectations подтверждает инварианты схемы. Отчёт пишется в
``lake/reports/quality/{dt}/report.json``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

from .validator import CleanBatch, QualityMetrics

REPORTS_PREFIX = "reports/quality"


def report_for_dataset(metrics: QualityMetrics, dataset_id: str, dt: date) -> dict[str, Any]:
    """Собрать отчёт о качестве по датасету (FR-020, FR-021)."""
    return {
        "dt": dt.isoformat(),
        "dataset_id": dataset_id,
        "quality_score": round(metrics.quality_score, 4),
        "missing_rate": round(metrics.missing_rate, 6),
        "dup_rate": round(metrics.dup_rate, 6),
        "outlier_rate": round(metrics.outlier_rate, 6),
        "gap_rate": round(metrics.gap_rate, 6),
        "anomalies_cnt": metrics.anomalies,
        "records": metrics.total,
    }


def run_great_expectations(frame: pd.DataFrame) -> dict[str, Any]:
    """Прогнать Great Expectations по silver-фрейму (``available``/``success``)."""
    if frame.empty:
        return {"available": True, "success": True, "expectations": []}
    try:
        import great_expectations as gx
    except ImportError:  # pragma: no cover - GE объявлен в зависимостях
        return {"available": False, "success": None, "expectations": []}

    try:
        context = gx.get_context(mode="ephemeral")
        data_source = context.data_sources.add_pandas("sputnik_silver")
        asset = data_source.add_dataframe_asset(name="silver")
        batch_definition = asset.add_batch_definition_whole_dataframe("silver_batch")
        batch = batch_definition.get_batch(batch_parameters={"dataframe": frame})
        suite = context.suites.add(gx.ExpectationSuite(name="silver_suite"))
        not_null = gx.expectations.ExpectColumnValuesToNotBeNull  # type: ignore[attr-defined]
        suite.add_expectation(not_null(column="reading_id"))
        suite.add_expectation(not_null(column="value"))
        result = batch.validate(suite)
        expectations = [
            {
                "expectation": str(getattr(item, "expectation_config", {}).get("type", "")),
                "success": bool(getattr(item, "success", False)),
            }
            for item in getattr(result, "results", [])
        ]
        return {
            "available": True,
            "success": bool(getattr(result, "success", False)),
            "expectations": expectations,
        }
    except Exception as error:  # граница внешнего инструмента
        return {"available": True, "success": None, "error": str(error), "expectations": []}


def build_reports(batch: CleanBatch, dt: date) -> dict[str, dict[str, Any]]:
    """Собрать отчёты по каждому датасету, включая проверку Great Expectations."""
    expects = run_great_expectations(batch.frame)
    reports: dict[str, dict[str, Any]] = {}
    for dataset_id, metrics in batch.metrics_by_dataset.items():
        report = report_for_dataset(metrics, dataset_id, dt)
        report["great_expectations"] = expects
        reports[dataset_id] = report
    return reports


def report_payload(dt: date, reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Единый JSON-документ отчёта ``report.json`` за дату."""
    return {
        "dt": dt.isoformat(),
        "datasets": {dataset_id: dict(report) for dataset_id, report in reports.items()},
    }


def report_key(dt: date) -> str:
    """Ключ объекта отчёта в MinIO ``reports/quality/{dt}/report.json``."""
    return f"{REPORTS_PREFIX}/{dt.isoformat()}/report.json"


async def write_reports(
    store: Any,
    bucket: str,
    dt: date,
    reports: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Записать ``report.json`` в MinIO; ``None`` — если отчётов нет."""
    if not reports:
        return None
    key = report_key(dt)
    body = json.dumps(report_payload(dt, reports), ensure_ascii=False, indent=2)
    await store.put_bytes(bucket, key, body.encode("utf-8"), "application/json")
    return key


__all__ = [
    "REPORTS_PREFIX",
    "build_reports",
    "report_for_dataset",
    "report_key",
    "report_payload",
    "run_great_expectations",
    "write_reports",
]
