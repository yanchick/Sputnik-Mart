"""Panel-личный кабинет: заказы, подписки и скачивания (T096)."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd
import panel as pn

from panel_shared.theme import apply_theme, hero, metric_card

from ..api_client import GatewayClient, GatewayError
from ..components.subscription_controls import build_subscription_controls


def build_account_page(client: GatewayClient) -> Any:
    """Собрать личный кабинет покупателя."""
    apply_theme()
    if client.token is None:
        return pn.Column(
            hero("Личный кабинет", "Спутник Данные"),
            pn.pane.Alert("Сначала войдите на странице каталога.", alert_type="warning"),
        )
    try:
        profile = client.me()
        orders = client.list_orders().get("data", [])
        subscriptions = client.list_subscriptions(str(profile["userId"])).get("data", [])
        downloads = client.list_downloads().get("data", [])
    except (GatewayError, httpx.HTTPError) as error:
        return pn.Column(hero("Личный кабинет", "Спутник Данные"), pn.pane.Alert(str(error)))

    orders_table = pn.widgets.Tabulator(value=pd.DataFrame(orders), disabled=True, page_size=10)
    subscriptions_table = pn.widgets.Tabulator(
        value=pd.DataFrame(subscriptions), disabled=True, page_size=10
    )
    downloads_table = pn.widgets.Tabulator(
        value=pd.DataFrame(downloads), disabled=True, page_size=10
    )

    active = [item for item in subscriptions if item.get("status") == "SUB_ACTIVE"]
    metrics = pn.Row(
        metric_card("Заказы", str(len(orders))),
        metric_card("Подписки", str(len(subscriptions))),
        metric_card("Активные", str(len(active))),
        metric_card("Скачивания", str(len(downloads))),
    )

    return pn.Column(
        hero(
            str(profile.get("displayName", "Покупатель")),
            f"{profile.get('email', '')} · {status_text(profile.get('status', ''))}",
        ),
        metrics,
        pn.pane.Markdown("### Заказы"),
        orders_table,
        pn.pane.Markdown("### Подписки"),
        subscriptions_table,
        build_subscription_controls(client, subscriptions),
        pn.pane.Markdown("### История скачиваний"),
        downloads_table,
    )


def status_text(status: str) -> str:
    """Человекочитаемый статус аккаунта."""
    return {"ACTIVE": "активен", "BLOCKED": "заблокирован"}.get(status, status)


__all__ = ["build_account_page", "status_text"]
