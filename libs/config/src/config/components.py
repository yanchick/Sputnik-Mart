"""Настройки по компонентам стека: Postgres, Redis, Kafka, ClickHouse, Mongo, MinIO.

Каждый компонент — отдельный ``pydantic-settings``-класс со своим
``env_prefix``; секреты приходят только из переменных окружения/``.env``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ENV_FILE = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
)


class ComponentSettings(BaseSettings):
    """База настроек компонента: читает ``.env`` и игнорирует лишние переменные."""

    model_config = _DEFAULT_ENV_FILE


def _component_config(prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class PostgresSettings(ComponentSettings):
    """PostgreSQL: схемы identity/catalog/orders/reviews."""

    model_config = _component_config("POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    user: str = "sputnik"
    password: str = "sputnik"
    database: str = "sputnik"
    url: str | None = None

    def async_dsn(self) -> str:
        """DSN для async SQLAlchemy (asyncpg)."""
        if self.url:
            return self.url
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def sync_dsn(self) -> str:
        """DSN для синхронных инструментов (Alembic offline, Airflow)."""
        return self.async_dsn().replace("+asyncpg", "+psycopg2")


class RedisSettings(ComponentSettings):
    """Redis: rate-limit, идемпотентность, сессии."""

    model_config = _component_config("REDIS_")

    url: str = "redis://localhost:6379/0"

    def dsn(self) -> str:
        """Вернуть строку подключения Redis."""
        return self.url


class KafkaSettings(ComponentSettings):
    """Redpanda (Kafka API): топики commerce.* и sensors.readings*."""

    model_config = _component_config("KAFKA_")

    bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str | None = None

    @property
    def servers(self) -> list[str]:
        """Разобрать список брокеров из строки ``host:port,host:port``."""
        return [item.strip() for item in self.bootstrap_servers.split(",") if item.strip()]


class ClickHouseSettings(ComponentSettings):
    """ClickHouse: gold-витрины fact_readings и mart_*."""

    model_config = _component_config("CLICKHOUSE_")

    host: str = "localhost"
    port: int = 8123
    user: str = "default"
    password: str = "clickhouse"
    database: str = "sputnik"
    secure: bool = False


class MongoSettings(ComponentSettings):
    """MongoDB: коллекция ``catalog_nosql.provider_meta``."""

    model_config = _component_config("MONGO_")

    uri: str = "mongodb://localhost:27017"
    database: str = "catalog_nosql"


class MinioSettings(ComponentSettings):
    """MinIO/S3: бакеты lake/samples/exports и префиксы слоёв."""

    model_config = _component_config("MINIO_")

    endpoint: str = "http://localhost:9000"
    root_user: str = "sputnik"
    root_password: str = "sputnik123"
    access_key: str = "sputnik"
    secret_key: str = "sputnik123"
    lake_bucket: str = "lake"
    samples_bucket: str = "samples"
    exports_bucket: str = "exports"
    region: str = "us-east-1"

    @property
    def buckets(self) -> tuple[str, ...]:
        """Список бакетов, которые обязан создать bootstrap."""
        return (self.lake_bucket, self.samples_bucket, self.exports_bucket)


class AirflowSettings(ComponentSettings):
    """Apache Airflow: локальная оркестрация DAGов."""

    model_config = _component_config("AIRFLOW_")

    home: str = "/opt/airflow"
    admin_user: str = Field(default="admin")
    admin_password: str = Field(default="admin")


class SimSettings(ComponentSettings):
    """Генераторы ``sim``: детерминированный seed."""

    model_config = _component_config("SIM_")

    seed: int = 42


__all__ = [
    "AirflowSettings",
    "ClickHouseSettings",
    "ComponentSettings",
    "KafkaSettings",
    "MinioSettings",
    "MongoSettings",
    "PostgresSettings",
    "RedisSettings",
    "SimSettings",
]
