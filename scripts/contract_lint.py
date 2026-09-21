#!/usr/bin/env python3
"""Линт и сверка машинных контрактов фичи ``001-sputnik-data-portal``.

Проверяет:
1) существование и разбор восьми контрактных YAML (OpenAPI/AsyncAPI);
2) валидацию OpenAPI через ``openapi-spec-validator``, если он установлен;
3) реконсиляцию contract↔model в обе стороны: перечисления, обязательные и
   объявленные поля Pydantic v2-моделей совпадают со схемами
   ``components.schemas`` (включая поля модели, забытые в контракте).
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from identity.schemas import (
    ApiKeyCreated,
    ApiKeyResolution,
    ApiKeyResolveRequest,
    ApiKeyView,
    LoginRequest,
    LoginResponse,
    SubscriptionView,
    UserProfile,
)
from pydantic import BaseModel
from review.main import CreateReviewRequest

from contracts import (
    ClickEventPayload,
    ClickSource,
    CreateOrderRequest,
    CreateSubscriptionRequest,
    Dataset,
    DatasetCategory,
    DeadReadingPayload,
    DeadReadingReason,
    DownloadEventPayload,
    ErrorDetail,
    ErrorEnvelope,
    EventEnvelope,
    FileFormat,
    FulfillOrderRequest,
    GeoPoint,
    Metric,
    Order,
    OrderAccess,
    OrderEventPayload,
    OrderStatus,
    PagedResponse,
    Pagination,
    QualityScoresUpdate,
    QualityScoresUpdated,
    ReviewEventPayload,
    SchemaField,
    SchemaFieldType,
    SensorReadingPayload,
    Subscription,
    SubscriptionEventPayload,
    SubscriptionStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = REPO_ROOT / "specs" / "001-sputnik-data-portal" / "contracts"

EXPECTED_CONTRACTS: dict[str, str] = {
    "openapi-catalog.yaml": "openapi",
    "openapi-order.yaml": "openapi",
    "openapi-delivery.yaml": "openapi",
    "openapi-identity.yaml": "openapi",
    "openapi-review.yaml": "openapi",
    "openapi-quality.yaml": "openapi",
    "asyncapi-commerce.yaml": "asyncapi",
    "asyncapi-content.yaml": "asyncapi",
}

MODEL_REGISTRY: dict[str, type[BaseModel] | type[Enum]] = {
    "Dataset": Dataset,
    "SchemaField": SchemaField,
    "DatasetCategory": DatasetCategory,
    "QualityScoresUpdate": QualityScoresUpdate,
    "QualityScoresUpdated": QualityScoresUpdated,
    "FileFormat": FileFormat,
    "Pagination": Pagination,
    "PagedResponse": PagedResponse,
    "Error": ErrorEnvelope,
    "ErrorDetail": ErrorDetail,
    "CreateOrderRequest": CreateOrderRequest,
    "CreateSubscriptionRequest": CreateSubscriptionRequest,
    "FulfillOrderRequest": FulfillOrderRequest,
    "Order": Order,
    "OrderAccess": OrderAccess,
    "Subscription": Subscription,
    "OrderStatus": OrderStatus,
    "SubscriptionStatus": SubscriptionStatus,
    "LoginRequest": LoginRequest,
    "LoginResponse": LoginResponse,
    "UserProfile": UserProfile,
    "SubscriptionView": SubscriptionView,
    "ApiKeyView": ApiKeyView,
    "ApiKeyCreated": ApiKeyCreated,
    "ApiKeyResolveRequest": ApiKeyResolveRequest,
    "ApiKeyResolution": ApiKeyResolution,
    "CreateReviewRequest": CreateReviewRequest,
    "EventEnvelope": EventEnvelope,
    "ClickEventPayload": ClickEventPayload,
    "OrderEventPayload": OrderEventPayload,
    "SubscriptionEventPayload": SubscriptionEventPayload,
    "DownloadEventPayload": DownloadEventPayload,
    "ReviewEventPayload": ReviewEventPayload,
    "SensorReadingPayload": SensorReadingPayload,
    "DeadReadingPayload": DeadReadingPayload,
    "Metric": Metric,
    "GeoPoint": GeoPoint,
}

# Встроенные перечисления свойств, не вынесенные в отдельную схему контракта.
PROPERTY_ENUMS: dict[tuple[str, str], type[Enum]] = {
    ("SchemaField", "type"): SchemaFieldType,
    ("DeadReadingPayload", "reason"): DeadReadingReason,
    ("ClickEventPayload", "source"): ClickSource,
}


def _openapi_validator() -> Callable[[Mapping[str, Any]], None] | None:
    """Вернуть валидатор OpenAPI, если пакет установлен, иначе ``None``."""
    try:
        module = importlib.import_module("openapi_spec_validator")
    except ImportError:
        return None
    validate = getattr(module, "validate", None)
    return validate if callable(validate) else None


def _resolve_pointer(document: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    """Разрешить локальную ссылку ``#/components/schemas/...``."""
    if not ref.startswith("#/"):
        return {}
    node: Any = document
    for part in ref[2:].split("/"):
        if not isinstance(node, Mapping) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, Mapping) else {}


def _resolve_schema(document: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    """Схлопнуть ``$ref`` и ``allOf`` в эффективную схему для сверки."""
    if "$ref" in schema:
        return _resolve_schema(document, _resolve_pointer(document, str(schema["$ref"])))
    if "allOf" not in schema:
        return dict(schema)

    properties: dict[str, Any] = {}
    required: list[str] = []
    for part in schema["allOf"]:
        resolved = _resolve_schema(document, part)
        properties.update(resolved.get("properties", {}))
        required.extend(resolved.get("required", []))
    merged = dict(schema)
    merged["properties"] = properties
    merged["required"] = required
    return merged


def _enum_values(enum_cls: type[Enum]) -> set[str]:
    return {str(member.value) for member in enum_cls}


def _check_enum(name: str, schema: Mapping[str, Any], model: type[Enum]) -> list[str]:
    declared = {str(item) for item in schema.get("enum", [])}
    expected = _enum_values(model)
    if declared == expected:
        return []
    return [f"{name}: enum {sorted(declared)} != model {sorted(expected)}"]


def _check_object(name: str, schema: Mapping[str, Any], model: type[BaseModel]) -> list[str]:
    """Сверить поля модели и схемы в обе стороны (m9)."""
    failures: list[str] = []
    fields = set(model.model_fields)
    properties = set(schema.get("properties", {}))
    required = set(schema.get("required", []))

    for field in sorted(required - fields):
        failures.append(f"{name}: обязательное поле '{field}' отсутствует в модели")
    for field in sorted(properties - fields):
        failures.append(f"{name}: поле '{field}' из контракта отсутствует в модели")
    for field in sorted(fields - properties):
        failures.append(f"{name}: поле модели '{field}' отсутствует в контракте")
    return failures


def _check_property_enums(name: str, schema: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    properties: Mapping[str, Any] = schema.get("properties", {})
    for (schema_name, property_name), enum_cls in PROPERTY_ENUMS.items():
        if schema_name != name or property_name not in properties:
            continue
        declared = {str(item) for item in properties[property_name].get("enum", [])}
        expected = _enum_values(enum_cls)
        if declared != expected:
            failures.append(
                f"{name}.{property_name}: enum {sorted(declared)} != model {sorted(expected)}"
            )
    return failures


def lint_contract(filename: str, root_key: str) -> list[str]:
    """Проверить один контракт и вернуть список нарушений (пусто — успех)."""
    path = CONTRACT_DIR / filename
    if not path.is_file():
        return [f"{filename}: файл не найден"]

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"{filename}: некорректный YAML: {error}"]

    if not isinstance(document, dict):
        return [f"{filename}: ожидался YAML-объект верхнего уровня"]

    if root_key not in document:
        return [f"{filename}: отсутствует корневой ключ '{root_key}'"]

    if root_key == "openapi":
        validator = _openapi_validator()
        if validator is not None:
            try:
                validator(document)
            except Exception as error:  # граница внешнего инструмента валидации
                return [f"{filename}: невалидная OpenAPI-схема: {error}"]

    schemas: Mapping[str, Any] = document.get("components", {}).get("schemas", {})
    failures: list[str] = []
    for schema_name, raw_schema in schemas.items():
        if not isinstance(raw_schema, Mapping):
            continue
        model = MODEL_REGISTRY.get(schema_name)
        if model is None:
            continue
        resolved = _resolve_schema(document, raw_schema)
        if "enum" in resolved:
            failures.extend(_check_enum(schema_name, resolved, model))  # type: ignore[arg-type]
            continue
        failures.extend(_check_object(schema_name, resolved, model))  # type: ignore[arg-type]
        failures.extend(_check_property_enums(schema_name, resolved))
    return [f"{filename}: {failure}" for failure in failures]


def main() -> int:
    """Запустить линт по всем контрактам и вернуть код выхода."""
    failures: list[str] = []
    for filename, root_key in EXPECTED_CONTRACTS.items():
        failures.extend(lint_contract(filename, root_key))

    if failures:
        for failure in failures:
            print(f"[contract-lint] FAIL: {failure}", file=sys.stderr)
        return 1

    print(f"[contract-lint] OK: проверено {len(EXPECTED_CONTRACTS)} контрактов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
