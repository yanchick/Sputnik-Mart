#!/usr/bin/env python3
"""Seed предсозданных демонстрационных аккаунтов (T053).

Самостоятельная регистрация не поддерживается: скрипт идемпотентно создаёт
фиксированный набор покупателей, их записи ``pii_vault`` и API-ключи. Повторный
запуск обновляет, но не дублирует данные. Шифрование PII на уровне приложения —
в сервисе identity (Phase 4); здесь хранится плейсхолдер-байты.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass, field

import asyncpg

from observability.pii import DEFAULT_PII_KEY, encrypt_pii, pii_key_ref

DEFAULT_DATABASE_URL = "postgresql+asyncpg://sputnik:sputnik@localhost:5432/sputnik"


def _pii_key() -> str:
    return os.environ.get("PII_ENCRYPTION_KEY", DEFAULT_PII_KEY)


@dataclass(frozen=True)
class DemoAccount:
    """Предсозданный демонстрационный покупатель."""

    user_id: str
    display_name: str
    email: str
    phone: str
    api_key_id: str
    api_key_prefix: str
    scopes: tuple[str, ...]
    key_ref: str = field(default_factory=lambda: pii_key_ref(_pii_key()))

    def email_enc(self) -> bytes:
        """Зашифрованный email для изолированного ``pii_vault``."""
        return encrypt_pii(self.email, _pii_key())

    def phone_enc(self) -> bytes:
        """Зашифрованный телефон для изолированного ``pii_vault``."""
        return encrypt_pii(self.phone, _pii_key())

    def api_key_hash(self) -> str:
        """Детерминированный хеш демонстрационного API-ключа."""
        digest = hashlib.sha256(f"{self.api_key_id}:{self.email}".encode())
        return digest.hexdigest()


DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount(
        user_id="us_demo_buyer",
        display_name="Демо Покупатель",
        email="buyer@sputnik.demo",
        phone="+79990000001",
        api_key_id="ak_demo_buyer",
        api_key_prefix="sk_demo_buy",
        scopes=("read", "download"),
    ),
    DemoAccount(
        user_id="us_demo_analyst",
        display_name="Демо Аналитик",
        email="analyst@sputnik.demo",
        phone="+79990000002",
        api_key_id="ak_demo_analyst",
        api_key_prefix="sk_demo_ana",
        scopes=("read",),
    ),
    DemoAccount(
        user_id="us_demo_partner",
        display_name="Демо Партнёр",
        email="partner@sputnik.demo",
        phone="+79990000003",
        api_key_id="ak_demo_partner",
        api_key_prefix="sk_demo_par",
        scopes=("read", "stream"),
    ),
)


def asyncpg_dsn(database_url: str) -> str:
    """Привести SQLAlchemy-DSN к формату, который понимает asyncpg."""
    return database_url.replace("+asyncpg", "")


async def _upsert_account(connection: asyncpg.Connection, account: DemoAccount) -> None:
    await connection.execute(
        """
        INSERT INTO identity.users (user_id, display_name, status)
        VALUES ($1, $2, 'ACTIVE')
        ON CONFLICT (user_id)
        DO UPDATE SET display_name = EXCLUDED.display_name, status = 'ACTIVE'
        """,
        account.user_id,
        account.display_name,
    )
    await connection.execute(
        """
        INSERT INTO identity.pii_vault (user_id, email_enc, phone_enc, key_ref)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id)
        DO UPDATE SET
            email_enc = EXCLUDED.email_enc,
            phone_enc = EXCLUDED.phone_enc,
            key_ref = EXCLUDED.key_ref
        """,
        account.user_id,
        account.email_enc(),
        account.phone_enc(),
        account.key_ref,
    )
    await connection.execute(
        """
        INSERT INTO identity.api_keys
            (key_id, user_id, key_prefix, key_hash, scopes, revoked_at)
        VALUES ($1, $2, $3, $4, $5, NULL)
        ON CONFLICT (key_id)
        DO UPDATE SET
            user_id = EXCLUDED.user_id,
            key_prefix = EXCLUDED.key_prefix,
            key_hash = EXCLUDED.key_hash,
            scopes = EXCLUDED.scopes,
            revoked_at = NULL
        """,
        account.api_key_id,
        account.user_id,
        account.api_key_prefix,
        account.api_key_hash(),
        list(account.scopes),
    )


async def seed_demo_accounts(
    database_url: str, accounts: Sequence[DemoAccount] = DEMO_ACCOUNTS
) -> list[str]:
    """Идемпотентно создать демо-аккаунты; вернуть их идентификаторы."""
    connection = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        for account in accounts:
            await _upsert_account(connection, account)
    finally:
        await connection.close()
    return [account.user_id for account in accounts]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed демонстрационных аккаунтов")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("POSTGRES_URL", DEFAULT_DATABASE_URL),
        help="SQLAlchemy DSN PostgreSQL (по умолчанию POSTGRES_URL)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Печать без записи в БД")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = _parse_args(argv)
    if args.dry_run:
        for account in DEMO_ACCOUNTS:
            print(f"[seed] would upsert {account.user_id} ({account.email})")
        return 0

    seeded = asyncio.run(seed_demo_accounts(str(args.dsn)))
    print(f"[seed] upserted {len(seeded)} demo accounts: {', '.join(seeded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
