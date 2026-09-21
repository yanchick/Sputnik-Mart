"""Panel live-график потребления SSE (T150, FR-035).

Страница подключается к ``/api/v1/streams/{subscriptionId}`` через
:class:`~web_vitrina.client_sse.SseStreamReader`, накапливает точки и рисует
ряд на Bokeh. Для тестов можно подменить источник кадров ``provider``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import panel as pn
from bokeh.models import ColumnDataSource
from bokeh.plotting import figure

from panel_shared.theme import COLORS, apply_theme, hero

from ..client_sse import SseStreamReader, StreamFrame

FrameProvider = Callable[[], list[StreamFrame]]
PERIOD_MS = 1000


def frame_point(frame: StreamFrame) -> float | None:
    """Значение чтения из кадра ``reading`` (``None`` для пингов и мусора)."""
    if frame.event != "reading":
        return None
    value = frame.data.get("value")
    if not isinstance(value, int | float):
        return None
    return float(value)


def update_chart(data: ColumnDataSource, frames: list[StreamFrame], *, offset: int) -> int:
    """Добавить точки кадров в источник данных; вернуть новый сдвиг."""
    xs = list(data.data["x"])
    ys = list(data.data["y"])
    cursor = offset
    for frame in frames:
        value = frame_point(frame)
        if value is None:
            continue
        cursor += 1
        xs.append(cursor)
        ys.append(value)
    data.data = {"x": xs, "y": ys}
    return cursor


def build_stream_page(
    client: Any | None = None,
    *,
    subscription_id: str = "",
    provider: FrameProvider | None = None,
) -> Any:
    """Собрать страницу живого графика подписки."""
    apply_theme()
    source = ColumnDataSource(data={"x": [], "y": []})
    chart = figure(
        title="Свежие чтения подписки",
        height=320,
        sizing_mode="stretch_width",
        background_fill_color="#FFFFFF",
    )
    chart.line("x", "y", source=source, line_width=2, color=COLORS["accent"])
    plot = pn.pane.Bokeh(chart)
    status = pn.pane.Markdown("Введите идентификатор подписки и подключитесь.")

    subscription_input = pn.widgets.TextInput(
        name="subscriptionId", value=subscription_id, placeholder="sub_..."
    )
    connect = pn.widgets.Button(name="Подключиться", button_type="primary")
    stop = pn.widgets.Button(name="Остановить", button_type="default")
    state: dict[str, Any] = {"offset": 0, "reader": None, "callback": None}

    def render(frames: list[StreamFrame]) -> None:
        if not frames:
            return
        state["offset"] = update_chart(source, frames, offset=int(state["offset"]))
        status.object = f"Получено кадров: **{state['offset']}**."

    def tick(event: Any = None) -> None:
        reader: SseStreamReader | None = state["reader"]
        if reader is None:
            return
        render(reader.poll())
        if reader.error:
            status.object = f"Поток оборван: {reader.error}"

    def on_connect(event: Any) -> None:
        if provider is not None:
            render(provider())
            return
        if client is None:
            status.object = "Нет клиента gateway для подключения."
            return
        reader = SseStreamReader(
            base_url=getattr(client, "gateway_url", None) or "http://localhost:8000",
            subscription_id=str(subscription_input.value or ""),
            token=getattr(client, "token", None),
        )
        state["reader"] = reader
        reader.start()
        status.object = "Подключение установлено."
        if state["callback"] is None:
            state["callback"] = pn.state.add_periodic_callback(tick, period=PERIOD_MS)

    def on_stop(event: Any) -> None:
        reader: SseStreamReader | None = state["reader"]
        if reader is not None:
            reader.stop()
        state["reader"] = None
        status.object = "Поток остановлен."

    connect.on_click(on_connect)
    stop.on_click(on_stop)
    return pn.Column(
        hero("Живой поток", "Свежие чтения подписки в реальном времени"),
        pn.Row(subscription_input, connect, stop, status),
        plot,
    )


__all__ = ["FrameProvider", "build_stream_page", "frame_point", "update_chart"]
