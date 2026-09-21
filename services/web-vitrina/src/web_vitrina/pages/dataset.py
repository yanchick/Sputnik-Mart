"""Panel-карточка датасета со схемой полей, покупкой и скачиванием (T095)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pandas as pd
import panel as pn

from panel_shared.theme import apply_theme, hero, metric_card

from ..api_client import GatewayClient, GatewayError
from ..components.review_form import build_review_form

FORMATS = ["CSV", "JSON", "PARQUET"]


def build_dataset_page(client: GatewayClient, dataset_id: str) -> Any:
    """Собрать карточку датасета с покупкой, скачиванием и отзывом."""
    apply_theme()
    status = pn.pane.Markdown("")
    try:
        card = client.get_dataset(dataset_id)
        schema = client.get_schema(dataset_id)
        sample = client.get_sample(dataset_id, "CSV")
    except (GatewayError, httpx.HTTPError) as error:
        return pn.Column(hero("Карточка датасета", dataset_id), pn.pane.Alert(str(error)))

    fmt = pn.widgets.Select(name="Формат", options=FORMATS, value="CSV")
    buy_button = pn.widgets.Button(name="Купить датасет", button_type="primary")
    download_button = pn.widgets.Button(name="Скачать", button_type="success")
    schema_table = pn.widgets.Tabulator(value=pd.DataFrame(schema), disabled=True, page_size=10)
    sample_pane = pn.pane.Str(sample, styles={"max-height": "220px", "overflow": "auto"})

    def on_buy(event: Any) -> None:
        try:
            order = client.create_order(dataset_id, idempotency_key=f"ui-{uuid.uuid4().hex[:8]}")
            status.object = f"Заказ **{order['orderId']}** создан и оплачен."
        except (GatewayError, httpx.HTTPError) as error:
            status.object = f"Ошибка покупки: {error}"

    def on_download(event: Any) -> None:
        try:
            content = client.download(dataset_id, str(fmt.value))
            status.object = f"Скачано {len(content)} байт в формате {fmt.value}."
        except (GatewayError, httpx.HTTPError) as error:
            status.object = f"Скачивание недоступно: {error}"

    buy_button.on_click(on_buy)
    download_button.on_click(on_download)

    metrics = pn.Row(
        metric_card("Цена, ₽", str(card.get("pricePerUnit", 0))),
        metric_card("Качество", f"{card.get('qualityScore', 0):.2f}"),
        metric_card("Частота, сек", str(card.get("frequencySec") or "—")),
        metric_card("Лицензия", str(card.get("licence", "—"))),
    )

    review_section = build_review_form(client, dataset_id)

    return pn.Column(
        hero(str(card.get("name", dataset_id)), str(card.get("volumeEstimate", ""))),
        metrics,
        pn.pane.Markdown(str(card.get("description", ""))),
        pn.Row(buy_button, fmt, download_button, status),
        pn.pane.Markdown("### Схема полей"),
        schema_table,
        pn.pane.Markdown("### Образец данных (CSV)"),
        sample_pane,
        review_section,
    )


__all__ = ["FORMATS", "build_dataset_page"]
