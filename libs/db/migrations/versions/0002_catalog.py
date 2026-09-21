"""Схема catalog: providers, datasets, dataset_fields.

Revision ID: 0002_catalog
Revises: 0001_identity
Create Date: 2026-09-18

План отката: ``downgrade`` удаляет таблицы и снимает схему ``catalog``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_catalog"
down_revision: str | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog")

    op.create_table(
        "providers",
        sa.Column("provider_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("meta_ref", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="status_valid"),
        schema="catalog",
    )

    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.Text(), primary_key=True),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("frequency_sec", sa.Integer(), nullable=True),
        sa.Column("volume_estimate", sa.Text(), nullable=True),
        sa.Column(
            "price_per_unit",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "quality_score",
            sa.Numeric(4, 3),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("licence", sa.Text(), nullable=False),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('WEATHER', 'AIR_QUALITY', 'ENERGY', 'TRANSPORT', 'COMMERCE')",
            name="category_valid",
        ),
        sa.CheckConstraint("quality_score BETWEEN 0 AND 1", name="quality_score_range"),
        sa.CheckConstraint("price_per_unit >= 0", name="price_non_negative"),
        sa.CheckConstraint("frequency_sec IS NULL OR frequency_sec > 0", name="frequency_positive"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["catalog.providers.provider_id"],
            name="fk_datasets_provider_id_providers",
            ondelete="RESTRICT",
        ),
        schema="catalog",
    )
    op.create_index("ix_catalog_datasets_category", "datasets", ["category"], schema="catalog")
    op.create_index(
        "ix_catalog_datasets_provider_id", "datasets", ["provider_id"], schema="catalog"
    )

    op.create_table(
        "dataset_fields",
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("nullable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "type IN ('STRING', 'INT', 'DOUBLE', 'BOOLEAN', 'DATETIME', 'GEO')",
            name="type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["catalog.datasets.dataset_id"],
            name="fk_dataset_fields_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dataset_id", "name", name="pk_dataset_fields"),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_table("dataset_fields", schema="catalog")
    op.drop_index("ix_catalog_datasets_provider_id", table_name="datasets", schema="catalog")
    op.drop_index("ix_catalog_datasets_category", table_name="datasets", schema="catalog")
    op.drop_table("datasets", schema="catalog")
    op.drop_table("providers", schema="catalog")
    op.execute("DROP SCHEMA IF EXISTS catalog")
