"""Схема reviews: reviews с CHECK (rating BETWEEN 1 AND 5).

Revision ID: 0004_reviews
Revises: 0003_orders
Create Date: 2026-09-18

План отката: ``downgrade`` удаляет таблицу и снимает схему ``reviews``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_reviews"
down_revision: str | None = "0003_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reviews")

    op.create_table(
        "reviews",
        sa.Column("review_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="rating_between_1_and_5"),
        sa.CheckConstraint(
            "sentiment IS NULL OR sentiment BETWEEN 0 AND 1", name="sentiment_range"
        ),
        schema="reviews",
    )
    op.create_index("ix_reviews_reviews_dataset_id", "reviews", ["dataset_id"], schema="reviews")
    op.create_index("ix_reviews_reviews_user_id", "reviews", ["user_id"], schema="reviews")


def downgrade() -> None:
    op.drop_index("ix_reviews_reviews_user_id", table_name="reviews", schema="reviews")
    op.drop_index("ix_reviews_reviews_dataset_id", table_name="reviews", schema="reviews")
    op.drop_table("reviews", schema="reviews")
    op.execute("DROP SCHEMA IF EXISTS reviews")
