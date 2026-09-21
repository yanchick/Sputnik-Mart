"""Репозитории identity: ``User``, ``ApiKey``, ``PiiVault`` (T069).

ORM-модели отображаются на таблицы схемы ``identity`` из миграции 0001.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, LargeBinary, Text, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from db.postgres import Base
from observability.pii import DEFAULT_PII_KEY, encrypt_pii

ACTIVE_STATUS = "ACTIVE"


class User(Base):
    """Покупатель портала (``identity.users``)."""

    __tablename__ = "users"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=ACTIVE_STATUS)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class PiiVault(Base):
    """Изолированное хранилище PII (``identity.pii_vault``)."""

    __tablename__ = "pii_vault"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    email_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_ref: Mapped[str] = mapped_column(Text, nullable=False)


class ApiKey(Base):
    """Машинный ключ доступа (``identity.api_keys``)."""

    __tablename__ = "api_keys"
    __table_args__ = {"schema": "identity"}

    key_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(Text), nullable=False, default=lambda: ["read"]
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        """Ключ активен, пока не отозван."""
        return self.revoked_at is None


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    """Найти пользователя по идентификатору."""
    return await session.get(User, user_id)


async def get_pii(session: AsyncSession, user_id: str) -> PiiVault | None:
    """Найти PII-запись пользователя."""
    return await session.get(PiiVault, user_id)


async def find_user_by_email(
    session: AsyncSession, email: str, key: str = DEFAULT_PII_KEY
) -> tuple[User, PiiVault] | None:
    """Найти пользователя по email, не расшифровывая весь vault.

    Сравниваются детерминированный шифротекст (актуальный формат) и открытый
    email (совместимость с записями до включения шифрования).
    """
    candidates = [encrypt_pii(email, key), email.encode("utf-8")]
    statement = (
        select(User, PiiVault)
        .join(PiiVault, PiiVault.user_id == User.user_id)
        .where(PiiVault.email_enc.in_(candidates))
    )
    row = (await session.execute(statement)).first()
    if row is None:
        return None
    return row[0], row[1]


async def list_api_keys(session: AsyncSession, user_id: str) -> list[ApiKey]:
    """Вернуть ключи пользователя, включая отозванные."""
    statement = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at)
    return list((await session.execute(statement)).scalars().all())


async def get_api_key_by_hash(session: AsyncSession, key_hash: str) -> ApiKey | None:
    """Найти ключ по хешу (для машинной аутентификации)."""
    statement = select(ApiKey).where(ApiKey.key_hash == key_hash)
    return (await session.execute(statement)).scalars().first()


async def add_api_key(session: AsyncSession, api_key: ApiKey) -> ApiKey:
    """Добавить новый машинный ключ."""
    session.add(api_key)
    await session.flush()
    return api_key


async def revoke_api_key(session: AsyncSession, user_id: str, key_id: str) -> bool:
    """Отозвать ключ пользователя; ``False``, если ключ не найден или уже отозван."""
    api_key = await session.get(ApiKey, key_id)
    if api_key is None or api_key.user_id != user_id or api_key.revoked_at is not None:
        return False
    api_key.revoked_at = datetime.now(UTC)
    await session.flush()
    return True


async def user_exists(session: AsyncSession, user_id: str) -> bool:
    """Проверить существование пользователя."""
    statement = select(User.user_id).where(User.user_id == user_id)
    return (await session.execute(statement)).first() is not None


__all__ = [
    "ACTIVE_STATUS",
    "ApiKey",
    "PiiVault",
    "User",
    "add_api_key",
    "find_user_by_email",
    "get_api_key_by_hash",
    "get_pii",
    "get_user",
    "list_api_keys",
    "revoke_api_key",
    "user_exists",
]
