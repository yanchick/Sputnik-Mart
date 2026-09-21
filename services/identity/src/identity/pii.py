"""Application-level шифрование PII и ссылка на ключ ``key_ref`` (T169).

PII покупателя не хранится в открытом виде: email и телефон шифруются
детерминированно (см. :mod:`observability.pii`), что позволяет искать учётную
запись по email равенством, не выводя персональные данные из ``pii_vault``.
``key_ref`` указывает на ключ в KMS-подобном хранилище и не содержит сам ключ.
"""

from __future__ import annotations

from dataclasses import dataclass

from observability.pii import (
    DEFAULT_PII_KEY,
    PiiCipherError,
    decrypt_pii,
    encrypt_pii,
    is_encrypted_pii,
    pii_key_ref,
)


@dataclass(frozen=True)
class PiiVaultCipher:
    """Шифр хранилища PII: ключ и производная ссылка ``key_ref``."""

    key: str = DEFAULT_PII_KEY

    @property
    def key_ref(self) -> str:
        """Ссылка на ключ для колонки ``pii_vault.key_ref``."""
        return pii_key_ref(self.key)

    def encrypt(self, plaintext: str) -> bytes:
        """Зашифровать значение PII для записи в vault."""
        return encrypt_pii(plaintext, self.key)

    def decrypt(self, token: bytes) -> str:
        """Расшифровать значение PII, поддержав незашифрованные legacy-записи."""
        return decrypt_pii(token, self.key)

    def lookup_token(self, plaintext: str) -> bytes:
        """Детерминированный шифротекст для поиска по равенству."""
        return encrypt_pii(plaintext, self.key)


def encrypt_email(email: str, key: str = DEFAULT_PII_KEY) -> bytes:
    """Зашифровать email покупателя."""
    return encrypt_pii(email, key)


def decrypt_email(token: bytes, key: str = DEFAULT_PII_KEY) -> str:
    """Расшифровать email покупателя."""
    return decrypt_pii(token, key)


def encrypt_phone(phone: str, key: str = DEFAULT_PII_KEY) -> bytes:
    """Зашифровать телефон покупателя."""
    return encrypt_pii(phone, key)


def decrypt_phone(token: bytes, key: str = DEFAULT_PII_KEY) -> str:
    """Расшифровать телефон покупателя."""
    return decrypt_pii(token, key)


__all__ = [
    "DEFAULT_PII_KEY",
    "PiiCipherError",
    "PiiVaultCipher",
    "decrypt_email",
    "decrypt_phone",
    "encrypt_email",
    "encrypt_phone",
    "is_encrypted_pii",
    "pii_key_ref",
]
