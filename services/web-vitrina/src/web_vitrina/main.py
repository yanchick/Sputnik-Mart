"""Panel-фасад «Спутник Данные»: каталог, карточка и кабинет (T094–T099)."""

from __future__ import annotations

import os
from typing import Any

import panel as pn

from observability import configure_logging, get_logger
from panel_shared.theme import apply_theme

from .api_client import GatewayClient
from .pages import (
    build_account_page,
    build_catalog_page,
    build_dataset_page,
    build_quality_dashboard,
    build_quality_page,
    build_stream_page,
)

_log = get_logger(__name__)

DEFAULT_DATASET_ID = "ds_weather-stations"


def create_app(client: GatewayClient | None = None) -> Any:
    """Собрать вкладки фасада: каталог, карточка, кабинет, качество и поток."""
    apply_theme()
    resolved = client or GatewayClient()
    tabs = pn.Tabs(
        ("Каталог", build_catalog_page(resolved)),
        ("Датасет", build_dataset_page(resolved, DEFAULT_DATASET_ID)),
        ("Кабинет", build_account_page(resolved)),
        ("Качество", build_quality_page()),
        ("Деградация", build_quality_dashboard()),
        ("Живой поток", build_stream_page(resolved)),
        dynamic=False,
    )
    return pn.Column(pn.pane.Markdown("# Спутник Данные — витрина"), tabs)


def main() -> None:
    """Запустить Panel-сервер фасада."""
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="web-vitrina")
    port = int(os.environ.get("SERVICE_PORT", "8000"))
    pn.serve(create_app(), address="0.0.0.0", port=port, show=False, title="Спутник Данные")


__all__ = ["DEFAULT_DATASET_ID", "create_app", "main"]
