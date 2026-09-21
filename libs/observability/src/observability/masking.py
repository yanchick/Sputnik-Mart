"""Маскирование PII во всех выгрузках (FR-028, SC-009).

PII не покидает изолированный ``identity.pii_vault``: любая выгрузка проходит
через :func:`sanitize_export_rows`, которая маскирует email вида ``***@domain``,
телефоны и email-подобные подстроки внутри текстовых полей.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .auth import mask_email

PII_FIELD_NAMES = frozenset(
    {"email", "e_mail", "phone", "phone_number", "phonenumber", "msisdn", "contact"}
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Ведущий ``+`` и отсутствие пробелов не дают замаскировать ISO-даты в тексте.
_PHONE_RE = re.compile(r"\+\d[\d()-]{6,13}\d")
_DIGITS_RE = re.compile(r"\d")


def mask_phone(phone: str) -> str:
    """Замаскировать телефон, оставив только последние две цифры."""
    digits = "".join(_DIGITS_RE.findall(phone))
    if len(digits) < 4:
        return "***"
    return f"+{digits[0]}***{digits[-2:]}"


def mask_text(text: str) -> str:
    """Заменить email и телефоны в свободном тексте на маскированные значения."""
    masked = _EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    return _PHONE_RE.sub(lambda match: mask_phone(match.group(0)), masked)


def mask_value(value: Any) -> Any:
    """Замаскировать значение по его виду: email, телефон или иной текст."""
    if not isinstance(value, str):
        return value
    if _EMAIL_RE.fullmatch(value):
        return mask_email(value)
    if _PHONE_RE.fullmatch(value) and _DIGITS_RE.search(value):
        return mask_phone(value)
    if _EMAIL_RE.search(value) or _PHONE_RE.search(value):
        return mask_text(value)
    return value


def mask_pii_field(value: Any) -> Any:
    """Замаскировать значение поля, явно объявленного персональным."""
    if not isinstance(value, str):
        return value
    if "@" in value:
        return mask_email(value) if _EMAIL_RE.fullmatch(value) else mask_text(value)
    if _DIGITS_RE.search(value):
        return mask_phone(value)
    return mask_value(value)


def mask_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Рекурсивно замаскировать PII в одной строке выгрузки."""
    masked: dict[str, Any] = {}
    for key, value in record.items():
        if key.lower() in PII_FIELD_NAMES:
            masked[key] = mask_pii_field(value)
        elif isinstance(value, Mapping):
            masked[key] = mask_record(value)
        elif isinstance(value, list):
            masked[key] = [
                mask_record(item) if isinstance(item, Mapping) else mask_value(item)
                for item in value
            ]
        elif isinstance(value, str):
            masked[key] = mask_text(value)
        else:
            masked[key] = value
    return masked


def sanitize_export_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Пропустить строки выгрузки через маскирование PII."""
    return [mask_record(row) for row in rows]


def contains_pii(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Проверить, остались ли в готовой выгрузке незамаскированные PII."""
    for row in rows:
        for value in row.values():
            if isinstance(value, str) and (
                _EMAIL_RE.search(value) is not None or _PHONE_RE.search(value) is not None
            ):
                return True
    return False


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
