"""ClickHouse-клиент: синхронный драйвер, обёрнутый в ``asyncio.to_thread``.

clickhouse-connect не имеет асинхронного API, поэтому все вызовы вынесены в
executor — в async-контуре блокирующего I/O нет.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from clickhouse_connect import get_client
from clickhouse_connect.driver.client import Client


class AsyncClickHouseClient:
    """Асинхронная обёртка над clickhouse-connect ``Client``."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def connect(
        cls,
        *,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "default",
        secure: bool = False,
        **kwargs: Any,
    ) -> AsyncClickHouseClient:
        """Создать подключение к ClickHouse."""
        client = get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            secure=secure,
            **kwargs,
        )
        return cls(client)

    async def execute(self, query: str, parameters: Mapping[str, Any] | None = None) -> Any:
        """Выполнить запрос и вернуть результат (в executor)."""
        return await asyncio.to_thread(self._client.query, query, parameters=dict(parameters or {}))

    async def command(self, query: str) -> None:
        """Выполнить DDL/DML-команду без результата (в executor)."""
        await asyncio.to_thread(self._client.command, query)

    async def insert(
        self,
        table: str,
        data: Sequence[Sequence[Any]],
        column_names: Sequence[str] | None = None,
    ) -> None:
        """Вставить строки в таблицу (в executor)."""
        names = list(column_names) if column_names is not None else None
        await asyncio.to_thread(self._client.insert, table, data, column_names=names)

    async def close(self) -> None:
        """Закрыть подключение (в executor)."""
        await asyncio.to_thread(self._client.close)


def create_client(
    *,
    host: str,
    port: int = 8123,
    username: str = "default",
    password: str = "",
    database: str = "default",
    secure: bool = False,
) -> AsyncClickHouseClient:
    """Фабрика асинхронного ClickHouse-клиента."""
    return AsyncClickHouseClient.connect(
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
        secure=secure,
    )


__all__ = ["AsyncClickHouseClient", "create_client"]
