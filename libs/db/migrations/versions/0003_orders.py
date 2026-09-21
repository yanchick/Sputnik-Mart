"""Схема orders: orders, subscriptions, downloads.

Revision ID: 0003_orders
Revises: 0002_catalog
Create Date: 2026-09-18

Инвариант: ``UNIQUE (user_id, idempotency_key)``.
План отката: ``downgrade`` удаляет таблицы и снимает схему ``orders``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_orders"
down_revision: str | None = "0002_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS orders")

    op.create_table(
        "orders",
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'RUB'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'ORDER_PENDING'")),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('ORDER_PENDING', 'ORDER_PAID', 'ORDER_FULFILLED', 'ORDER_CANCELLED')",
            name="status_valid",
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_id_idempotency_key"),
        schema="orders",
    )
    op.create_index("ix_orders_orders_user_id", "orders", ["user_id"], schema="orders")

    op.create_table(
        "subscriptions",
        sa.Column("subscription_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("interval_sec", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'SUB_ACTIVE'")),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('SUB_ACTIVE', 'SUB_PAUSED', 'SUB_CANCELLED')",
            name="status_valid",
        ),
        sa.CheckConstraint("interval_sec > 0", name="interval_positive"),
        schema="orders",
    )
    op.create_index(
        "ix_orders_subscriptions_user_id", "subscriptions", ["user_id"], schema="orders"
    )

    op.create_table(
        "downloads",
        sa.Column("download_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'REQUESTED'")),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("format IN ('CSV', 'JSON', 'PARQUET')", name="format_valid"),
        sa.CheckConstraint("status IN ('REQUESTED', 'DONE', 'FAILED')", name="status_valid"),
        schema="orders",
    )
    op.create_index("ix_orders_downloads_user_id", "downloads", ["user_id"], schema="orders")


def downgrade() -> None:
    op.drop_index("ix_orders_downloads_user_id", table_name="downloads", schema="orders")
    op.drop_table("downloads", schema="orders")
    op.drop_index("ix_orders_subscriptions_user_id", table_name="subscriptions", schema="orders")
    op.drop_table("subscriptions", schema="orders")
    op.drop_index("ix_orders_orders_user_id", table_name="orders", schema="orders")
    op.drop_table("orders", schema="orders")
    op.execute("DROP SCHEMA IF EXISTS orders")
