"""Mongo-клиент на Motor для гибких метаданных провайдеров."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


def create_mongo_client(uri: str) -> AsyncIOMotorClient[Any]:
    """Создать асинхронный Motor-клиент (без подключения до первого запроса)."""
    return AsyncIOMotorClient(uri, uuidRepresentation="standard")


def get_database(client: AsyncIOMotorClient[Any], name: str) -> AsyncIOMotorDatabase[Any]:
    """Вернуть базу по имени."""
    return client[name]


async def ping(client: AsyncIOMotorClient[Any]) -> bool:
    """Проверить доступность Mongo командой ``ping``."""
    result = await client.admin.command("ping")
    return bool(result.get("ok"))


async def close_mongo(client: AsyncIOMotorClient[Any]) -> None:
    """Закрыть Motor-клиент."""
    client.close()


__all__ = ["close_mongo", "create_mongo_client", "get_database", "ping"]
