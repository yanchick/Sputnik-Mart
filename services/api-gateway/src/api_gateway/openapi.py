"""Сборка объединённого OpenAPI gateway и Swagger/OpenAPI UI (T093)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONTRACT_FILES = (
    "openapi-catalog.yaml",
    "openapi-order.yaml",
    "openapi-delivery.yaml",
    "openapi-identity.yaml",
    "openapi-review.yaml",
    "openapi-quality.yaml",
)
COMPONENT_SECTIONS = ("schemas", "parameters", "responses", "securitySchemes", "requestBodies")


def _merge_component_section(target: dict[str, Any], source: dict[str, Any]) -> None:
    for section in COMPONENT_SECTIONS:
        values = source.get(section)
        if isinstance(values, dict):
            target.setdefault(section, {}).update(values)


def load_gateway_openapi(contract_dir: Path) -> dict[str, Any]:
    """Объединить OpenAPI-контракты сервисов в один документ gateway."""
    merged: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "Спутник Данные — API Gateway",
            "version": "1.0.0",
            "description": "Единая точка входа фасада витрины данных «Спутник Данные».",
        },
        "servers": [{"url": "http://localhost:8000", "description": "Локальный gateway"}],
        "paths": {},
        "components": {},
    }
    for filename in CONTRACT_FILES:
        path = contract_dir / filename
        if not path.is_file():
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        merged["paths"].update(document.get("paths", {}))
        components = document.get("components", {})
        if isinstance(components, dict):
            _merge_component_section(merged["components"], components)
    merged["components"].setdefault("securitySchemes", {}).update(
        {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-Api-Key"},
        }
    )
    return merged


__all__ = ["CONTRACT_FILES", "load_gateway_openapi"]
