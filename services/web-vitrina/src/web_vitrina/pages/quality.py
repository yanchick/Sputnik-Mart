"""Panel-страница качества данных (T132, FR-021).

Показывает показатели ``missing/dup/outlier/anomalies`` и рейтинг качества,
согласованный с каталогом и отчётом validation-service.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx
import pandas as pd
import panel as pn

from panel_shared.theme import apply_theme, hero

DEFAULT_GATEWAY_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


def quality_base_url() -> str:
    """Базовый URL Quality-page: gateway в приоритете, прямой сервис — фолбэк.

    В compose задан ``GATEWAY_URL`` — страница ходит через фасад по
    ``/api/v1/quality``, как остальные страницы Panel. ``QUALITY_URL``
    остаётся для прямого обращения к quality-service при отладке.
    """
    return (
        os.environ.get("GATEWAY_URL") or os.environ.get("QUALITY_URL") or DEFAULT_GATEWAY_URL
    ).rstrip("/")


DEFAULT_QUALITY_URL = quality_base_url()
_COLUMNS = [
    "datasetId",
    "name",
    "qualityScore",
    "missingRate",
    "dupRate",
    "outlierRate",
    "anomaliesCnt",
]

QualityProvider = Callable[[], list[dict[str, Any]]]


def fetch_quality(base_url: str | None = None) -> list[dict[str, Any]]:
    """Получить срез качества через gateway (или напрямую, если URL задан явно)."""
    resolved = (base_url or quality_base_url()).rstrip("/")
    with httpx.Client(base_url=resolved, timeout=15.0) as client:
        response = client.get(f"{API_PREFIX}/quality")
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return [dict(item) for item in payload.get("data", [])]


def build_quality_page(provider: QualityProvider | None = None) -> Any:
    """Собрать Panel-страницу качества с обновлением по кнопке."""
    apply_theme()
    load = provider or fetch_quality
    status = pn.pane.Markdown("Показатели качества за последний прогон конвейера.")
    refresh_button = pn.widgets.Button(name="Обновить", button_type="primary")
    table = pn.widgets.Tabulator(value=pd.DataFrame(columns=_COLUMNS), disabled=True, page_size=20)

    def reload(event: Any = None) -> None:
        try:
            rows = [{key: row.get(key) for key in _COLUMNS} for row in load()]
            table.value = pd.DataFrame(rows, columns=_COLUMNS)
            status.object = f"Датасетов: **{len(rows)}**."
        except (httpx.HTTPError, ValueError) as error:
            status.object = f"Ошибка загрузки качества: {error}"

    refresh_button.on_click(reload)
    reload()
    return pn.Column(
        hero("Качество данных", "Пропуски, дубли, выбросы и аномалии по датасетам"),
        pn.Row(refresh_button, status),
        table,
    )


__all__ = [
    "API_PREFIX",
    "DEFAULT_GATEWAY_URL",
    "DEFAULT_QUALITY_URL",
    "QualityProvider",
    "build_quality_page",
    "fetch_quality",
    "quality_base_url",
]
