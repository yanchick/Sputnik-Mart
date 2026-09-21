"""Unit-тесты конфигурации (T035)."""

from __future__ import annotations

import pytest

from config import (
    Environment,
    KafkaSettings,
    MinioSettings,
    PostgresSettings,
    RuntimeProfile,
    Settings,
    get_settings,
)

pytestmark = pytest.mark.unit


def test_postgres_defaults_and_dsn() -> None:
    settings = PostgresSettings()

    assert settings.port == 5432
    assert settings.async_dsn().startswith("postgresql+asyncpg://")
    assert settings.sync_dsn().startswith("postgresql+psycopg2://")


def test_postgres_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://u:p@db:5432/portal")
    settings = PostgresSettings()

    assert settings.async_dsn() == "postgresql+asyncpg://u:p@db:5432/portal"
    assert settings.sync_dsn() == "postgresql+psycopg2://u:p@db:5432/portal"


def test_kafka_servers_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "a:9092, b:9092")

    assert KafkaSettings().servers == ["a:9092", "b:9092"]


def test_minio_buckets_default() -> None:
    assert MinioSettings().buckets == ("lake", "samples", "exports")


def test_settings_profile_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROFILE", "demo")
    monkeypatch.setenv("ENVIRONMENT", "demo")

    settings = Settings()

    assert settings.app.profile is RuntimeProfile.DEMO
    assert settings.app.environment is Environment.DEMO


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second
