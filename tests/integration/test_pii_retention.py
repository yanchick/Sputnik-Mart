"""Интеграционный тест автоудаления PII по сроку 12 месяцев (T158, FR-037, SC-013)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from identity.pii import encrypt_email
from identity.retention import delete_expired_pii, retention_cutoff
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

_OLD_USER = "us_retention_old"
_RECENT_USER = "us_retention_recent"


async def _insert_user(session: AsyncSession, user_id: str, created_at: datetime) -> None:
    await session.execute(
        text(
            "INSERT INTO identity.users (user_id, display_name, status, created_at) "
            "VALUES (:user_id, :name, 'ACTIVE', :created_at) "
            "ON CONFLICT (user_id) DO UPDATE SET created_at = EXCLUDED.created_at"
        ),
        {"user_id": user_id, "name": "Retention Test", "created_at": created_at},
    )
    await session.execute(
        text(
            "INSERT INTO identity.pii_vault (user_id, email_enc, phone_enc, key_ref) "
            "VALUES (:user_id, :email, :phone, 'kms://sputnik/pii/test') "
            "ON CONFLICT (user_id) DO UPDATE SET email_enc = EXCLUDED.email_enc"
        ),
        {
            "user_id": user_id,
            "email": encrypt_email(f"{user_id}@sputnik.demo"),
            "phone": encrypt_email("+79990000000"),
        },
    )


async def _count_pii(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM identity.pii_vault WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    return int(result.scalar_one())


def test_retention_cutoff_is_twelve_months_back() -> None:
    cutoff = retention_cutoff(datetime(2026, 9, 18, tzinfo=UTC))
    assert cutoff == datetime(2025, 9, 18, tzinfo=UTC)


async def test_expired_pii_is_deleted_recent_is_kept(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        await _insert_user(session, _OLD_USER, now - timedelta(days=400))
        await _insert_user(session, _RECENT_USER, now - timedelta(days=5))
        await session.commit()

    async with session_factory() as session:
        deleted = await delete_expired_pii(session, now=now)
        await session.commit()
        assert deleted >= 1
        assert await _count_pii(session, _OLD_USER) == 0
        assert await _count_pii(session, _RECENT_USER) == 1
