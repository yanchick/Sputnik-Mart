"""Схема identity: users, pii_vault, api_keys.

Revision ID: 0001_identity
Revises:
Create Date: 2026-09-18

План отката: ``downgrade`` удаляет таблицы в порядке зависимостей и снимает схему.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")

    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'BLOCKED')", name="status_valid"),
        schema="identity",
    )

    op.create_table(
        "pii_vault",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("email_enc", sa.LargeBinary(), nullable=False),
        sa.Column("phone_enc", sa.LargeBinary(), nullable=True),
        sa.Column("key_ref", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.user_id"],
            name="fk_pii_vault_user_id_users",
            ondelete="CASCADE",
        ),
        schema="identity",
    )

    op.create_table(
        "api_keys",
        sa.Column("key_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['read']::text[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.user_id"],
            name="fk_api_keys_user_id_users",
            ondelete="CASCADE",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_identity_api_keys_user_id",
        "api_keys",
        ["user_id"],
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("ix_identity_api_keys_user_id", table_name="api_keys", schema="identity")
    op.drop_table("api_keys", schema="identity")
    op.drop_table("pii_vault", schema="identity")
    op.drop_table("users", schema="identity")
    op.execute("DROP SCHEMA IF EXISTS identity")
