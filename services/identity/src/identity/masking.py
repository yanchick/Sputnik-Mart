"""Маскирование email/телефона во всех выгрузках (T170, FR-028, SC-009).

Политика PII принадлежит identity: замаскированные значения вида ``***@domain``
и обезличенный телефон применяются ко всем выгрузкам. Канонические примитивы
живут в :mod:`observability.masking` (общий слой), а этот модуль фиксирует
identity-семантику и переиспользуется тестами и сервисами.
"""

from __future__ import annotations

from observability.masking import (
    PII_FIELD_NAMES,
    contains_pii,
    mask_email,
    mask_phone,
    mask_pii_field,
    mask_record,
    mask_text,
    mask_value,
    sanitize_export_rows,
)

__all__ = [
    "PII_FIELD_NAMES",
    "contains_pii",
    "mask_email",
    "mask_phone",
    "mask_pii_field",
    "mask_record",
    "mask_text",
    "mask_value",
    "sanitize_export_rows",
]
