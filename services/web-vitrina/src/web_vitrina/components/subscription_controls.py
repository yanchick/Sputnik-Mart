"""Panel-управление статусами подписки (T154, FR-009).

Покупатель приостанавливает, возобновляет и отменяет подписку прямо из
кабинета. Доступ к купленным данным при этом сохраняется; отмена терминальна.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import panel as pn

from panel_shared.theme import status_badge

from ..api_client import GatewayClient, GatewayError

_ALLOWED = {
    "SUB_ACTIVE": ("pause", "cancel"),
    "SUB_PAUSED": ("resume", "cancel"),
    "SUB_CANCELLED": (),
}


def build_subscription_controls(
    client: GatewayClient,
    subscriptions: list[dict[str, Any]],
    on_change: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """Собрать панель управления подписками покупателя."""
    if not subscriptions:
        return pn.pane.Markdown("Активных подписок нет.")

    options = {
        f"{item.get('subscriptionId')} · {item.get('datasetId')}": str(item.get("subscriptionId"))
        for item in subscriptions
    }
    selector = pn.widgets.Select(name="Подписка", options=options)
    pause = pn.widgets.Button(name="Приостановить", button_type="warning")
    resume = pn.widgets.Button(name="Возобновить", button_type="success")
    cancel = pn.widgets.Button(name="Отменить", button_type="danger")
    status = pn.pane.Markdown("")

    by_id = {str(item.get("subscriptionId")): item for item in subscriptions}

    def apply(action: str, event: Any) -> None:
        subscription_id = str(selector.value)
        try:
            if action == "pause":
                payload = client.pause_subscription(subscription_id)
            elif action == "resume":
                payload = client.resume_subscription(subscription_id)
            else:
                payload = client.cancel_subscription(subscription_id)
        except (GatewayError, httpx.HTTPError) as error:
            status.object = f"Не удалось изменить статус: {error}"
            return
        status.object = f"Статус: {payload.get('status')}"
        if on_change is not None:
            on_change(payload)

    def handler(action: str) -> Callable[[Any], None]:
        def on_click(event: Any) -> None:
            apply(action, event)

        return on_click

    for button, action in ((pause, "pause"), (resume, "resume"), (cancel, "cancel")):
        button.on_click(handler(action))

    def refresh(event: Any = None) -> None:
        current = by_id.get(str(selector.value), {})
        current_status = str(current.get("status", ""))
        allowed = _ALLOWED.get(current_status, ())
        pause.disabled = "pause" not in allowed
        resume.disabled = "resume" not in allowed
        cancel.disabled = "cancel" not in allowed
        status.object = f"Текущий статус: {current_status or '—'}"

    selector.param.watch(lambda event: refresh(), "value")
    refresh()
    return pn.Column(
        pn.pane.Markdown("### Управление подпиской"),
        selector,
        pn.Row(pause, resume, cancel),
        status,
        status_badge(str((by_id.get(str(selector.value)) or {}).get("status", ""))),
    )


__all__ = ["build_subscription_controls"]
