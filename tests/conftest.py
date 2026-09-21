"""Общие фикстуры и настройки тестов монорепозитория «Спутник Данные»."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from db.postgres import create_engine, create_session_factory, dispose_engine
from sim.buyers import seed_buyers
from sim.providers import seed_catalog
from support import Apps, build_apps

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "libs" / "db" / "migrations"
CONTRACT_DIR = REPO_ROOT / "specs" / "001-sputnik-data-portal" / "contracts"


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Вернуть абсолютный путь к корню монорепозитория."""
    return REPO_ROOT


def _docker_available() -> bool:
    try:
        from testcontainers.core.docker_client import DockerClient

        return bool(DockerClient().client.ping())
    except Exception:
        return False


DOCKER_AVAILABLE = _docker_available()


def require_docker() -> None:
    """Пропустить тест, если Docker-демон недоступен."""
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker daemon недоступен — тест пропущен")


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    """Поднять общий Postgres-контейнер для тестов US1."""
    require_docker()
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


def _alembic_config() -> AlembicConfig:
    config = AlembicConfig(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


async def _seed(dsn: str) -> None:
    engine = create_engine(dsn)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await seed_catalog(session)
            await seed_buyers(session)
            await session.commit()
    finally:
        await dispose_engine(engine)


@pytest.fixture(scope="session")
def seeded_database(postgres_dsn: str) -> Iterator[str]:
    """Применить миграции и наполнить каталог/покупателей один раз."""
    previous = os.environ.get("POSTGRES_URL")
    os.environ["POSTGRES_URL"] = postgres_dsn
    try:
        command.upgrade(_alembic_config(), "head")
        asyncio.run(_seed(postgres_dsn))
        yield postgres_dsn
    finally:
        if previous is None:
            os.environ.pop("POSTGRES_URL", None)
        else:
            os.environ["POSTGRES_URL"] = previous


@pytest.fixture
async def session_factory(
    seeded_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Фабрика сессий, привязанная к event loop текущего теста."""
    engine = create_engine(seeded_database)
    try:
        yield create_session_factory(engine)
    finally:
        await dispose_engine(engine)


@pytest.fixture
async def apps(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Apps]:
    """Набор US1-приложений поверх общей БД."""
    resolved = Settings()
    built = build_apps(session_factory, resolved)
    try:
        yield built
    finally:
        await built.gateway_client.aclose()
        await built.peer_client.aclose()
