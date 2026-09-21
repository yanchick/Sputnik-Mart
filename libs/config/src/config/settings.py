"""Корневые настройки приложения и профилей запуска ``base|adv|demo``."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .components import (
    AirflowSettings,
    ClickHouseSettings,
    KafkaSettings,
    MinioSettings,
    MongoSettings,
    PostgresSettings,
    RedisSettings,
    SimSettings,
)


class Environment(StrEnum):
    """Режим окружения."""

    LOCAL = "local"
    TEST = "test"
    DEMO = "demo"
    PRODUCTION = "production"


class RuntimeProfile(StrEnum):
    """Профиль запуска docker compose."""

    BASE = "base"
    ADV = "adv"
    DEMO = "demo"


class AppSettings(BaseSettings):
    """Общие настройки портала (без префикса компонента)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    profile: RuntimeProfile = RuntimeProfile.BASE
    auth_secret: str = "sputnik-demo-secret"
    demo_password: str = "demo"
    demo_auto_pay: bool = True
    rate_limit_per_minute: int = 120
    rate_limit_window_seconds: int = 60
    pii_encryption_key: str = "sputnik-demo-pii-key"
    pii_retention_months: int = 12


class Settings(BaseModel):
    """Агрегированные настройки: приложение и все компоненты стека."""

    app: AppSettings = Field(default_factory=AppSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    clickhouse: ClickHouseSettings = Field(default_factory=ClickHouseSettings)
    mongo: MongoSettings = Field(default_factory=MongoSettings)
    minio: MinioSettings = Field(default_factory=MinioSettings)
    airflow: AirflowSettings = Field(default_factory=AirflowSettings)
    sim: SimSettings = Field(default_factory=SimSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Вернуть кэшированные настройки, собранные из окружения и ``.env``."""
    return Settings()


__all__ = [
    "AppSettings",
    "Environment",
    "RuntimeProfile",
    "Settings",
    "get_settings",
]
