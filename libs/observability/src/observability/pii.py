"""Детерминированное application-level шифрование PII (FR-028, FR-037).

PII хранится изолированно в ``identity.pii_vault``. Шифрование детерминированное:
одинаковый открытый текст с одним ключом даёт одинаковый шифротекст, поэтому
покупателя можно искать по email равенством, не выводя PII наружу. Целостность
подтверждается HMAC-тегом: повреждённый или подменённый шифротекст приводит к
явной ошибке :class:`PiiCipherError`, а не к тихой подмене данных.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Final

#: Демо-ключ по умолчанию. Существует только для локального стенда:
#: вне демо обязательно переопределяется через ``PII_ENCRYPTION_KEY`` /
#: ``Settings.app.pii_encryption_key`` (FR-028, FR-037).
DEFAULT_PII_KEY: Final[str] = "sputnik-demo-pii-key"
PII_CIPHER_VERSION: Final[bytes] = b"pii_v1:"
_NONCE_SIZE = 8
_TAG_SIZE = 16
_BLOCK_SIZE = 32


class PiiCipherError(ValueError):
    """Ошибка расшифровки PII: повреждённый или подменённый шифротекст."""


def _key_bytes(key: str) -> bytes:
    if not key:
        raise PiiCipherError("Ключ шифрования PII не может быть пустым")
    return hashlib.sha256(key.encode("utf-8")).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    produced = 0
    counter = 0
    while produced < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        produced += _BLOCK_SIZE
        counter += 1
    return b"".join(blocks)[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(left ^ right for left, right in zip(data, stream, strict=True))


def encrypt_pii(plaintext: str, key: str = DEFAULT_PII_KEY) -> bytes:
    """Зашифровать значение PII детерминированным ключевым потоком с HMAC-тегом."""
    if plaintext == "":
        return b""
    key_bytes = _key_bytes(key)
    raw = plaintext.encode("utf-8")
    nonce = hmac.new(key_bytes, b"nonce:" + raw, hashlib.sha256).digest()[:_NONCE_SIZE]
    ciphertext = _xor(raw, _keystream(key_bytes, nonce, len(raw)))
    tag = hmac.new(key_bytes, nonce + ciphertext, hashlib.sha256).digest()[:_TAG_SIZE]
    return PII_CIPHER_VERSION + nonce + tag + ciphertext


def is_encrypted_pii(token: bytes) -> bool:
    """Признак нового формата шифротекста (для совместимости с legacy-записями)."""
    return token.startswith(PII_CIPHER_VERSION)


def decrypt_pii(token: bytes, key: str = DEFAULT_PII_KEY) -> str:
    """Расшифровать значение PII; legacy-запись без тега читается как UTF-8."""
    if token == b"":
        return ""
    if not is_encrypted_pii(token):
        return token.decode("utf-8", errors="replace")

    key_bytes = _key_bytes(key)
    payload = token[len(PII_CIPHER_VERSION) :]
    if len(payload) < _NONCE_SIZE + _TAG_SIZE:
        raise PiiCipherError("Шифротекст PII короче минимальной длины")

    nonce = payload[:_NONCE_SIZE]
    tag = payload[_NONCE_SIZE : _NONCE_SIZE + _TAG_SIZE]
    ciphertext = payload[_NONCE_SIZE + _TAG_SIZE :]
    expected = hmac.new(key_bytes, nonce + ciphertext, hashlib.sha256).digest()[:_TAG_SIZE]
    if not hmac.compare_digest(tag, expected):
        raise PiiCipherError("HMAC-тег PII не совпал: данные повреждены или ключ неверен")

    stream = _keystream(key_bytes, nonce, len(ciphertext))
    return _xor(ciphertext, stream).decode("utf-8")


def pii_key_ref(key: str = DEFAULT_PII_KEY) -> str:
    """Вернуть ссылку на ключ вида ``kms://sputnik/pii/<fingerprint>``.

    Сам ключ в ``key_ref`` не хранится — только его отпечаток.
    """
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"kms://sputnik/pii/{fingerprint}"


__all__ = [
    "DEFAULT_PII_KEY",
    "PII_CIPHER_VERSION",
    "PiiCipherError",
    "decrypt_pii",
    "encrypt_pii",
    "is_encrypted_pii",
    "pii_key_ref",
]
