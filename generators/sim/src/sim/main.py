"""Точка входа seed профиля ``base``: датасеты и демо-аккаунты (T100)."""

from __future__ import annotations

import asyncio
import os

from db.postgres import create_engine, create_session_factory, dispose_engine

from .buyers import seed_buyers
from .providers import seed_catalog

DEFAULT_SEED = 42


async def seed_all(dsn: str, seed: int = DEFAULT_SEED) -> None:
    """Идемпотентно наполнить ``catalog`` и ``identity`` демо-данными."""
    engine = create_engine(dsn)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            datasets = await seed_catalog(session, seed)
            users = await seed_buyers(session)
            await session.commit()
        print(f"[sim] seeded {len(datasets)} datasets and {len(users)} buyers")
    finally:
        await dispose_engine(engine)


def main() -> None:
    """Запустить seed из ``POSTGRES_URL`` (используется compose-сервисом ``seed``)."""
    dsn = os.environ.get("POSTGRES_URL")
    if not dsn:
        raise SystemExit("POSTGRES_URL is required")
    asyncio.run(seed_all(dsn, int(os.environ.get("SIM_SEED", str(DEFAULT_SEED)))))


__all__ = ["DEFAULT_SEED", "main", "seed_all"]
