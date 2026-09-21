"""Panel-страницы фасада «Спутник Данные»."""

from __future__ import annotations

from .account import build_account_page
from .catalog import build_catalog_page
from .dataset import build_dataset_page
from .quality import build_quality_page
from .quality_dashboard import build_quality_dashboard
from .stream import build_stream_page

__all__ = [
    "build_account_page",
    "build_catalog_page",
    "build_dataset_page",
    "build_quality_dashboard",
    "build_quality_page",
    "build_stream_page",
]
