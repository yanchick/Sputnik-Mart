"""Panel-страница входа и каталога датасетов (T094)."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd
import panel as pn

from panel_shared.theme import apply_theme, hero

from ..api_client import GatewayClient, GatewayError

CATEGORIES = ["Все", "WEATHER", "AIR_QUALITY", "ENERGY", "TRANSPORT", "COMMERCE"]
_COLUMNS = ["datasetId", "name", "category", "pricePerUnit", "qualityScore", "licence"]


def build_catalog_page(client: GatewayClient) -> Any:
    """Собрать страницу входа и каталога с фильтрами."""
    apply_theme()
    status = pn.pane.Markdown("Войдите под предсозданным демонстрационным аккаунтом.")
    email = pn.widgets.TextInput(name="Email", value="buyer@sputnik.demo")
    password = pn.widgets.PasswordInput(name="Пароль", value="demo")
    login_button = pn.widgets.Button(name="Войти", button_type="primary")
    category = pn.widgets.Select(name="Категория", options=CATEGORIES, value="Все")
    min_quality = pn.widgets.FloatSlider(
        name="Минимальный рейтинг качества", start=0.0, end=1.0, step=0.05, value=0.0
    )
    refresh_button = pn.widgets.Button(name="Обновить каталог")
    table = pn.widgets.Tabulator(
        value=pd.DataFrame(columns=_COLUMNS), pagination="remote", page_size=20, disabled=True
    )

    def reload(event: Any = None) -> None:
        try:
            selected = None if category.value == "Все" else str(category.value)
            payload = client.list_datasets(
                category=selected, min_quality=float(min_quality.value or 0.0) or None
            )
            rows = [{key: row.get(key) for key in _COLUMNS} for row in payload.get("data", [])]
            table.value = pd.DataFrame(rows, columns=_COLUMNS)
        except (GatewayError, httpx.HTTPError) as error:
            status.object = f"Ошибка каталога: {error}"

    def on_login(event: Any) -> None:
        try:
            payload = client.login(str(email.value), str(password.value))
            status.object = f"Вы вошли как **{payload['user']['displayName']}**."
            reload()
        except (GatewayError, httpx.HTTPError) as error:
            status.object = f"Ошибка входа: {error}"

    login_button.on_click(on_login)
    refresh_button.on_click(reload)
    category.param.watch(lambda _: reload(), "value")
    min_quality.param.watch(lambda _: reload(), "value")

    return pn.Column(
        hero("Каталог данных", "Витрина датасетов маркетплейса «Спутник Данные»"),
        pn.Row(pn.Column(email, password, login_button), status),
        pn.Row(category, min_quality, refresh_button),
        table,
    )


__all__ = ["CATEGORIES", "build_catalog_page"]
