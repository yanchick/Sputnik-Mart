"""Unit-тесты Panel Quality-dashboard: расчёт деградации и сборка страницы (T175)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from web_vitrina.pages.quality import fetch_quality, quality_base_url
from web_vitrina.pages.quality_dashboard import (
    DEGRADATION_THRESHOLD,
    build_degradation_rows,
    build_quality_dashboard,
    degradation_ratio,
)

pytestmark = pytest.mark.unit


def test_quality_base_url_prefers_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """QR-2: в приоритете ``GATEWAY_URL``, как у остальных страниц Panel."""
    monkeypatch.setenv("GATEWAY_URL", "http://api-gateway:8000/")
    monkeypatch.setenv("QUALITY_URL", "http://quality:8000")
    assert quality_base_url() == "http://api-gateway:8000"


def test_quality_base_url_falls_back_to_direct_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QR-2: ``QUALITY_URL`` — осознанный фолбэк для прямой отладки."""
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.setenv("QUALITY_URL", "http://quality:8000/")
    assert quality_base_url() == "http://quality:8000"


def test_quality_base_url_defaults_to_local_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """QR-2: без env страница всё равно смотрит в фасад, а не в порт 8007."""
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.delenv("QUALITY_URL", raising=False)
    assert quality_base_url() == "http://localhost:8000"


def test_fetch_quality_calls_gateway_quality_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """QR-2: страница запрашивает ``/api/v1/quality`` у переданного базы-URL."""
    captured: dict[str, str] = {}

    class _StubClient:
        def __init__(self, base_url: str, timeout: float) -> None:
            captured["base_url"] = base_url
            captured["timeout"] = str(timeout)

        def __enter__(self) -> _StubClient:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, path: str) -> httpx.Response:
            captured["path"] = path
            request = httpx.Request("GET", f"http://gateway:8000{path}")
            return httpx.Response(200, json={"data": [{"datasetId": "ds_a"}]}, request=request)

    monkeypatch.setattr("web_vitrina.pages.quality.httpx.Client", _StubClient)
    rows = fetch_quality("http://gateway:8000/")

    assert rows == [{"datasetId": "ds_a"}]
    assert captured["base_url"] == "http://gateway:8000"
    assert captured["path"] == "/api/v1/quality"


def test_degradation_ratio_is_clamped() -> None:
    assert degradation_ratio(0.9) == 0.0
    assert degradation_ratio(1.0) == 0.0
    assert degradation_ratio(0.45) == pytest.approx(0.5)
    assert degradation_ratio(0.0) == pytest.approx(1.0)
    assert degradation_ratio(0.5, baseline=0.0) == 0.0


def test_build_degradation_rows_flags_threshold() -> None:
    rows = build_degradation_rows(
        [
            {"datasetId": "ds_ok", "name": "OK", "qualityScore": 0.95},
            {"datasetId": "ds_bad", "name": "Bad", "qualityScore": 0.4},
        ]
    )

    by_id = {row.dataset_id: row for row in rows}
    assert by_id["ds_ok"].is_degraded is False
    assert by_id["ds_bad"].is_degraded is True
    assert by_id["ds_bad"].degradation > DEGRADATION_THRESHOLD


def test_build_quality_dashboard_renders() -> None:
    def provider() -> list[dict[str, Any]]:
        return [{"datasetId": "ds_ok", "name": "OK", "qualityScore": 0.95}]

    dashboard = build_quality_dashboard(provider)
    assert dashboard is not None
    assert len(dashboard.objects) >= 3
