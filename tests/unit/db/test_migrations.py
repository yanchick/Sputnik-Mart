"""Тесты миграций Alembic без живого Postgres (offline SQL) (T047)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "libs" / "db" / "migrations"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"

EXPECTED_REVISIONS = ["0001_identity", "0002_catalog", "0003_orders", "0004_reviews"]


def _config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://sputnik:sputnik@localhost:5432/sputnik"
    )
    return config


def test_migration_files_exist() -> None:
    for revision in EXPECTED_REVISIONS:
        assert (VERSIONS_DIR / f"{revision}.py").is_file()


def test_revision_chain_is_linear() -> None:
    script = ScriptDirectory.from_config(_config())

    assert script.get_heads() == [EXPECTED_REVISIONS[-1]]
    assert script.get_bases() == [EXPECTED_REVISIONS[0]]

    revisions = [item.revision for item in script.walk_revisions()]
    assert revisions == list(reversed(EXPECTED_REVISIONS))

    for item in script.walk_revisions():
        assert callable(item.module.upgrade)
        assert callable(item.module.downgrade)


def test_offline_upgrade_renders_schemas_and_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(_config(), "head", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE SCHEMA IF NOT EXISTS identity" in sql
    assert "CREATE SCHEMA IF NOT EXISTS catalog" in sql
    assert "CREATE SCHEMA IF NOT EXISTS orders" in sql
    assert "CREATE SCHEMA IF NOT EXISTS reviews" in sql
    assert "CREATE TABLE identity.users" in sql
    assert "CREATE TABLE identity.pii_vault" in sql
    assert "CREATE TABLE identity.api_keys" in sql
    assert "CREATE TABLE catalog.datasets" in sql
    assert "CREATE TABLE catalog.dataset_fields" in sql
    assert "CREATE TABLE orders.orders" in sql
    assert "CREATE TABLE orders.subscriptions" in sql
    assert "CREATE TABLE orders.downloads" in sql
    assert "CREATE TABLE reviews.reviews" in sql
    assert "uq_orders_user_id_idempotency_key" in sql
    assert "CHECK (rating BETWEEN 1 AND 5)" in sql


def test_offline_downgrade_drops_schemas(capsys: pytest.CaptureFixture[str]) -> None:
    command.downgrade(_config(), "0004_reviews:base", sql=True)

    sql = capsys.readouterr().out
    assert "DROP SCHEMA IF EXISTS identity" in sql
    assert "DROP SCHEMA IF EXISTS catalog" in sql
    assert "DROP SCHEMA IF EXISTS orders" in sql
    assert "DROP SCHEMA IF EXISTS reviews" in sql
