#!/usr/bin/env python3
"""Подготовка предзаготовленных данных профиля ``demo`` (T174, FR-030, SC-010).

Идемпотентно наполняет Postgres каталогом и демо-аккаунтами, а MinIO —
bronze-партицией чтений и партнёрскими CSV. Одинаковый ``seed`` даёт идентичный
результат (FR-029), поэтому профиль ``demo`` воспроизводим.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from config import Settings, get_settings
from db import (
    create_engine,
    create_object_store,
    create_session_factory,
    dispose_engine,
)
from sim.buyers import build_behavior, seed_buyers
from sim.providers import build_catalog, seed_catalog
from sim.sensors import generate_readings

DEFAULT_SEED = 42
DEFAULT_PERIODS = 24
DEMO_DATE = date(2026, 9, 1)
DEMO_DATASET_PREFIX = "ds_"
PARTNER_ROWS = 5


def demo_readings(seed: int = DEFAULT_SEED, periods: int = DEFAULT_PERIODS) -> list[dict[str, Any]]:
    """Детерминированные чтения датчиков для bronze-партиции профиля demo."""
    return generate_readings(
        seed=seed,
        periods=periods,
        start=datetime(DEMO_DATE.year, DEMO_DATE.month, DEMO_DATE.day, tzinfo=UTC),
    )


def readings_ndjson(readings: Sequence[dict[str, Any]]) -> bytes:
    """Сериализовать чтения в NDJSON (по строке на запись)."""
    payload = "\n".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False, default=str) for record in readings
    )
    return (payload + ("\n" if payload else "")).encode("utf-8")


def partner_csv_bytes(provider_id: str, seed: int = DEFAULT_SEED) -> bytes:
    """Детерминированный партнёрский CSV поставщика."""
    generator = random.Random(f"{provider_id}:{seed}")
    lines = ["stationId,metric,value,measuredAt"]
    for index in range(PARTNER_ROWS):
        lines.append(
            ",".join(
                [
                    f"st_{provider_id}_{index}",
                    "TEMPERATURE",
                    f"{generator.uniform(-20, 30):.2f}",
                    datetime(2026, 9, 1, index, tzinfo=UTC).isoformat(),
                ]
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


async def prepare_demo_data(
    settings: Settings,
    *,
    seed: int = DEFAULT_SEED,
    periods: int = DEFAULT_PERIODS,
) -> dict[str, int]:
    """Идемпотентно подготовить Postgres и MinIO для профиля demo."""
    engine = create_engine(settings.postgres.async_dsn())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            dataset_ids = await seed_catalog(session, seed)
            user_ids = await seed_buyers(session)
            await session.commit()
    finally:
        await dispose_engine(engine)

    store = create_object_store(
        endpoint_url=settings.minio.endpoint,
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name=settings.minio.region,
    )
    lake = settings.minio.lake_bucket
    await store.ensure_bucket(lake)

    readings = demo_readings(seed, periods)
    await store.put_bytes(
        lake,
        f"bronze/demo/{DEMO_DATE.isoformat()}/readings.ndjson",
        readings_ndjson(readings),
        content_type="application/x-ndjson",
    )
    behavior = build_behavior(seed=seed)
    await store.put_bytes(
        lake,
        f"gold/demo/{DEMO_DATE.isoformat()}/buyers_behavior.json",
        json.dumps(behavior, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )

    providers = build_catalog(seed)
    for provider in providers:
        await store.put_bytes(
            lake,
            f"partner/{provider.provider_id}/{DEMO_DATE.isoformat()}.csv",
            partner_csv_bytes(provider.provider_id, seed),
            content_type="text/csv",
        )

    print(
        "[demo-data] prepared "
        f"datasets={len(dataset_ids)} buyers={len(user_ids)} "
        f"readings={len(readings)} partners={len(providers)}"
    )
    return {
        "datasets": len(dataset_ids),
        "buyers": len(user_ids),
        "readings": len(readings),
        "partners": len(providers),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Подготовить предзаготовленные данные demo")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--periods", type=int, default=DEFAULT_PERIODS)
    parser.add_argument("--dry-run", action="store_true", help="Печать плана без записи")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = _parse_args(argv)
    if args.dry_run:
        print(
            f"[demo-data] would seed datasets/buyers and {args.periods} readings (seed={args.seed})"
        )
        return 0

    result = asyncio.run(prepare_demo_data(get_settings(), seed=args.seed, periods=args.periods))
    print(f"[demo-data] done: {result}")
    return 0


if __name__ == "__main__":  # pragma: no cover - ручной запуск
    raise SystemExit(main())
