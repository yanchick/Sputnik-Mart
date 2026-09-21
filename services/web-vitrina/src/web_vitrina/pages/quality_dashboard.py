"""Panel Quality-dashboard с показателями деградации (T175, FR-026, SC-011).

Сводит срез качества и SLA-порог: показывает средний рейтинг, число
деградировавших датасетов и таблицу с относительной деградацией, согласованную
с алертом Grafana ``sputnik_quality_degradation_ratio``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pandas as pd
import panel as pn

from panel_shared.theme import COLORS, apply_theme, hero, metric_card

from .quality import QualityProvider, fetch_quality

QUALITY_BASELINE = 0.9
DEGRADATION_THRESHOLD = 0.15
_TABLE_COLUMNS = ["datasetId", "name", "qualityScore", "degradation", "alert"]


@dataclass(frozen=True)
class DegradationRow:
    """Строка дашборда деградации по датасету."""

    dataset_id: str
    name: str
    quality_score: float
    degradation: float

    @property
    def is_degraded(self) -> bool:
        """Превышен ли порог относительной деградации."""
        return self.degradation > DEGRADATION_THRESHOLD


def degradation_ratio(score: float, baseline: float = QUALITY_BASELINE) -> float:
    """Относительная деградация ``[0..1]``; при нулевом baseline — ``0``."""
    if baseline <= 0.0:
        return 0.0
    return min(max((baseline - score) / baseline, 0.0), 1.0)


def build_degradation_rows(rows: list[dict[str, Any]]) -> list[DegradationRow]:
    """Построить строки дашборда из среза quality-service."""
    result: list[DegradationRow] = []
    for row in rows:
        score = float(row.get("qualityScore", row.get("quality_score", 0.0)))
        result.append(
            DegradationRow(
                dataset_id=str(row.get("datasetId", row.get("dataset_id", ""))),
                name=str(row.get("name", "")),
                quality_score=score,
                degradation=degradation_ratio(score),
            )
        )
    return result


def _table_dataframe(rows: list[DegradationRow]) -> pd.DataFrame:
    payload = [
        {
            "datasetId": row.dataset_id,
            "name": row.name,
            "qualityScore": round(row.quality_score, 4),
            "degradation": round(row.degradation, 4),
            "alert": "ДЕГРАДАЦИЯ" if row.is_degraded else "норма",
        }
        for row in rows
    ]
    return pd.DataFrame(payload, columns=_TABLE_COLUMNS)


def build_quality_dashboard(provider: QualityProvider | None = None) -> Any:
    """Собрать Panel Quality-dashboard с показателями деградации."""
    apply_theme()
    load = provider or fetch_quality
    status = pn.pane.Markdown("Показатели деградации по последнему прогону.")
    cards = pn.Row(sizing_mode="stretch_width")
    table = pn.widgets.Tabulator(
        value=pd.DataFrame(columns=_TABLE_COLUMNS), disabled=True, page_size=20
    )
    refresh_button = pn.widgets.Button(name="Обновить", button_type="primary")

    def reload(event: Any = None) -> None:
        try:
            rows = build_degradation_rows(load())
        except (httpx.HTTPError, ValueError) as error:
            status.object = f"Ошибка загрузки: {error}"
            return
        degraded = [row for row in rows if row.is_degraded]
        average = sum(row.quality_score for row in rows) / len(rows) if rows else 0.0
        cards.objects = [
            metric_card("Датасетов", str(len(rows))),
            metric_card("Среднее качество", f"{average:.2f}"),
            metric_card(
                "Деградация",
                f"<span style='color:{COLORS['danger']}'>{len(degraded)}</span>",
            ),
        ]
        status.object = (
            f"Деградировало **{len(degraded)}** из **{len(rows)}** датасетов."
            if rows
            else "Нет данных о качестве."
        )
        table.value = _table_dataframe(rows)

    refresh_button.on_click(reload)
    reload()
    return pn.Column(
        hero(
            "Мониторинг деградации",
            "Средний рейтинг, деградация и срабатывание алерта по порогу 15%",
        ),
        pn.Row(refresh_button, status),
        cards,
        table,
    )


__all__ = [
    "DEGRADATION_THRESHOLD",
    "QUALITY_BASELINE",
    "DegradationRow",
    "build_degradation_rows",
    "build_quality_dashboard",
    "degradation_ratio",
]
