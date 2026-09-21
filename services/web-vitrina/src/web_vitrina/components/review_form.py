"""Panel-форма отзыва с оценкой 1–5 (T097)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import panel as pn

from ..api_client import GatewayClient, GatewayError


def build_review_form(
    client: GatewayClient,
    dataset_id: str,
    on_submitted: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """Форма отзыва: оценка 1–5, текст и отправка в review-сервис."""
    rating = pn.widgets.IntSlider(name="Оценка", start=1, end=5, value=5)
    text = pn.widgets.TextAreaInput(name="Текст отзыва", placeholder="Что понравилось?", rows=3)
    submit = pn.widgets.Button(name="Отправить отзыв", button_type="primary")
    status = pn.pane.Markdown("")

    def on_click(event: Any) -> None:
        try:
            payload = client.create_review(
                dataset_id, int(rating.value or 1), str(text.value) or None
            )
            status.object = "Отзыв сохранён. В рейтинг идёт только последний отзыв."
            if on_submitted is not None:
                on_submitted(payload)
        except (GatewayError, httpx.HTTPError) as error:
            status.object = f"Не удалось отправить отзыв: {error}"

    submit.on_click(on_click)
    return pn.Column(pn.pane.Markdown("### Оставить отзыв"), rating, text, submit, status)


__all__ = ["build_review_form"]
