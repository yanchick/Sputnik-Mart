"""Общая Panel-тема и компоненты «Спутник Данные» (T099)."""

from __future__ import annotations

from typing import Any

import panel as pn

FONT_STACK = "'Manrope', 'Inter', system-ui, sans-serif"
COLORS: dict[str, str] = {
    "ink": "#101828",
    "accent": "#5B4BFF",
    "accent_soft": "#EEECFF",
    "success": "#12B76A",
    "warning": "#F79009",
    "danger": "#F04438",
    "muted": "#667085",
}


def apply_theme() -> None:
    """Включить дизайн-систему Material и адаптивную вёрстку."""
    pn.extension(design="material", sizing_mode="stretch_width")


def hero(title: str, subtitle: str) -> pn.Column:
    """Крупный заголовок страницы с подзаголовком."""
    return pn.Column(
        pn.pane.HTML(
            f"<h1 style='font-family:{FONT_STACK};color:{COLORS['ink']};margin:0'>{title}</h1>"
        ),
        pn.pane.Markdown(f"<span style='color:{COLORS['muted']}'>{subtitle}</span>"),
        styles={"padding": "8px 0 16px 0"},
    )


def metric_card(label: str, value: str) -> pn.Column:
    """Карточка метрики для кабинета и каталога."""
    return pn.Column(
        pn.pane.Markdown(f"**{label}**"),
        pn.pane.HTML(f"<span style='font-size:1.6rem;color:{COLORS['accent']}'>{value}</span>"),
        styles={
            "background": COLORS["accent_soft"],
            "border-radius": "12px",
            "padding": "12px 16px",
        },
    )


def status_badge(status: str) -> Any:
    """Цветной бейдж статуса заказа или подписки."""
    palette = {
        "ORDER_PAID": COLORS["success"],
        "ORDER_FULFILLED": COLORS["success"],
        "SUB_ACTIVE": COLORS["success"],
        "ORDER_PENDING": COLORS["warning"],
        "SUB_PAUSED": COLORS["warning"],
        "ORDER_CANCELLED": COLORS["danger"],
        "SUB_CANCELLED": COLORS["danger"],
    }
    color = palette.get(status, COLORS["muted"])
    return pn.pane.HTML(
        f"<span style='background:{color};color:white;border-radius:999px;"
        f"padding:2px 10px;font-size:0.8rem'>{status}</span>"
    )


__all__ = [
    "COLORS",
    "FONT_STACK",
    "apply_theme",
    "hero",
    "metric_card",
    "status_badge",
]
