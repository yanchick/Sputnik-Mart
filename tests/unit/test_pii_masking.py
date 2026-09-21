"""Unit-тест маскирования PII в выгрузках ``***@domain`` (T157, FR-028, SC-009)."""

from __future__ import annotations

import pytest
from identity.masking import (
    contains_pii,
    mask_email,
    mask_phone,
    mask_record,
    mask_text,
    sanitize_export_rows,
)
from identity.pii import (
    PiiCipherError,
    PiiVaultCipher,
    decrypt_email,
    decrypt_phone,
    encrypt_email,
    encrypt_phone,
)

from observability.pii import PII_CIPHER_VERSION, decrypt_pii, encrypt_pii

pytestmark = pytest.mark.unit

KEY = "unit-pii-key"


def test_mask_email_and_phone() -> None:
    assert mask_email("buyer@sputnik.demo") == "***@sputnik.demo"
    assert mask_phone("+79990000001") == "+7***01"
    assert mask_phone("123") == "***"


def test_mask_text_keeps_dates_intact() -> None:
    raw = "buyer@sputnik.demo +79990000001 2026-09-01T00:00:00"
    masked = mask_text(raw)

    assert "buyer@sputnik" not in masked
    assert "***@sputnik.demo" in masked
    assert "2026-09-01T00:00:00" in masked


def test_sanitize_export_rows_removes_pii_recursively() -> None:
    rows = [
        {
            "readingId": "rd_1",
            "email": "buyer@sputnik.demo",
            "phone": "+79990000001",
            "owner": {"contact": "analyst@sputnik.demo"},
            "note": "связь +79990000002",
            "measuredAt": "2026-09-01T00:00:00",
        }
    ]
    sanitized = sanitize_export_rows(rows)

    assert not contains_pii(sanitized)
    assert sanitized[0]["email"] == "***@sputnik.demo"
    assert sanitized[0]["owner"]["contact"] == "***@sputnik.demo"
    assert sanitized[0]["measuredAt"] == "2026-09-01T00:00:00"
    assert "buyer@" not in str(sanitized)


def test_mask_record_masks_pii_by_field_name_even_without_plus() -> None:
    masked = mask_record({"phone": "89990000001", "city": "Москва"})

    assert masked["phone"] != "89990000001"
    assert masked["city"] == "Москва"


def test_pii_cipher_round_trip_is_deterministic() -> None:
    cipher = PiiVaultCipher(key=KEY)
    token = cipher.encrypt("buyer@sputnik.demo")

    assert token == cipher.encrypt("buyer@sputnik.demo")
    assert token != b"buyer@sputnik.demo"
    assert cipher.decrypt(token) == "buyer@sputnik.demo"
    assert cipher.key_ref.startswith("kms://sputnik/pii/")
    assert KEY not in cipher.key_ref


def test_pii_cipher_rejects_tampered_ciphertext() -> None:
    token = encrypt_email("buyer@sputnik.demo", KEY)
    tampered = token[:-1] + bytes([token[-1] ^ 0xFF])

    with pytest.raises(PiiCipherError):
        decrypt_email(tampered, KEY)


def test_pii_cipher_reads_legacy_plaintext() -> None:
    assert decrypt_email(b"buyer@sputnik.demo", KEY) == "buyer@sputnik.demo"


def test_pii_cipher_edge_cases_fail_loud() -> None:
    assert encrypt_pii("", KEY) == b""
    assert decrypt_pii(b"", KEY) == ""

    with pytest.raises(PiiCipherError):
        encrypt_pii("x", "")
    with pytest.raises(PiiCipherError):
        decrypt_pii(PII_CIPHER_VERSION + b"short", KEY)

    cipher = PiiVaultCipher(key=KEY)
    assert cipher.lookup_token("buyer@sputnik.demo") == cipher.encrypt("buyer@sputnik.demo")
    phone_token = encrypt_phone("+79990000001", KEY)
    assert decrypt_phone(phone_token, KEY) == "+79990000001"
