"""Индексы MongoDB для коллекции ``catalog_nosql.provider_meta``."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, TEXT, IndexModel

PROVIDER_META_COLLECTION = "provider_meta"


def provider_meta_indexes() -> list[IndexModel]:
    """Определения индексов provider_meta: уникальность, поиск и вложенность."""
    return [
        IndexModel(
            [("providerId", ASCENDING)],
            unique=True,
            name="uq_provider_meta_provider_id",
        ),
        IndexModel(
            [("name", TEXT), ("tags", TEXT)],
            name="ix_provider_meta_text",
        ),
        IndexModel(
            [("devices.stationId", ASCENDING)],
            name="ix_provider_meta_device_station",
        ),
        IndexModel(
            [("status", ASCENDING)],
            name="ix_provider_meta_status",
        ),
    ]


async def ensure_provider_meta_indexes(database: AsyncIOMotorDatabase[Any]) -> list[str]:
    """Создать индексы коллекции provider_meta; вернуть их имена."""
    collection = database[PROVIDER_META_COLLECTION]
    names = await collection.create_indexes(provider_meta_indexes())
    return list(names)


__all__ = [
    "PROVIDER_META_COLLECTION",
    "ensure_provider_meta_indexes",
    "provider_meta_indexes",
]
