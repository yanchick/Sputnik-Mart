"""S3/MinIO-клиент для озера и выгрузок.

boto3 — синхронный; все вызовы выполняются в executor, чтобы не блокировать
async-контур. Префиксы соответствуют медальон-схеме и партнёрским выгрузкам.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

PREFIX_BRONZE = "bronze"
PREFIX_SILVER = "silver"
PREFIX_REPORTS = "reports"
PREFIX_EXPORTS = "exports"
PREFIX_SAMPLES = "samples"
PREFIX_PARTNER = "partner"

_OBJECT_STORE_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
)


class AsyncObjectStore:
    """Асинхронная обёртка над синхронным boto3 S3-клиентом."""

    def __init__(self, client: BaseClient) -> None:
        self._client = client

    @classmethod
    def connect(
        cls,
        *,
        endpoint_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = "us-east-1",
    ) -> AsyncObjectStore:
        """Создать S3-клиент, совместимый с MinIO (path-style addressing)."""
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
            config=_OBJECT_STORE_CONFIG,
        )
        return cls(client)

    def _bucket_exists_sync(self, bucket: str) -> bool:
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "NotFound"}:
                return False
            raise
        return True

    async def bucket_exists(self, bucket: str) -> bool:
        """Проверить существование бакета."""
        return await asyncio.to_thread(self._bucket_exists_sync, bucket)

    async def ensure_bucket(self, bucket: str) -> bool:
        """Создать бакет, если его нет; ``True`` — бакет создан сейчас."""
        if await self.bucket_exists(bucket):
            return False
        await asyncio.to_thread(self._client.create_bucket, Bucket=bucket)
        return True

    async def put_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Загрузить объект в бакет."""
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        """Скачать объект из бакета."""
        response = await asyncio.to_thread(self._client.get_object, Bucket=bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        """Список ключей бакета по префиксу."""
        response = await asyncio.to_thread(
            self._client.list_objects_v2, Bucket=bucket, Prefix=prefix
        )
        contents: Sequence[dict[str, Any]] = response.get("Contents", [])
        return [str(item["Key"]) for item in contents]

    async def presign_get(self, bucket: str, key: str, *, expires_in: int = 3600) -> str:
        """Сгенерировать подписанную ссылку на скачивание."""
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def create_object_store(
    *,
    endpoint_url: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    region_name: str = "us-east-1",
) -> AsyncObjectStore:
    """Фабрика S3/MinIO-клиента."""
    return AsyncObjectStore.connect(
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
    )


__all__ = [
    "PREFIX_BRONZE",
    "PREFIX_EXPORTS",
    "PREFIX_PARTNER",
    "PREFIX_REPORTS",
    "PREFIX_SAMPLES",
    "PREFIX_SILVER",
    "AsyncObjectStore",
    "create_object_store",
]
