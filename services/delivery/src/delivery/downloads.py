"""История скачиваний и событие ``commerce.downloads`` (T087)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import CommerceTopic, DownloadEventPayload, FileFormat

STATUS_DONE = "DONE"


@dataclass(frozen=True)
class DownloadRecord:
    """Зафиксированный факт скачивания."""

    download_id: str
    user_id: str
    dataset_id: str
    format: str
    size: int
    requested_at: datetime


class DownloadPublisher(Protocol):
    """Абстракция публикации события скачивания."""

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        """Опубликовать событие."""
        ...


class NullDownloadPublisher:
    """No-op публикация без Redpanda (профиль ``base``)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], str]] = []

    async def publish(self, topic: str, payload: Mapping[str, Any], key: str) -> None:
        self.published.append((topic, dict(payload), key))


async def record_download(
    session: AsyncSession,
    *,
    user_id: str,
    dataset_id: str,
    fmt: FileFormat,
    size: int,
) -> DownloadRecord:
    """Записать историю скачивания со статусом ``DONE``."""
    download_id = f"dl_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    statement = text("""
        INSERT INTO orders.downloads
            (download_id, user_id, dataset_id, format, bytes, status, requested_at)
        VALUES
            (:download_id, :user_id, :dataset_id, :format, :size, 'DONE', :requested_at)
        """)
    await session.execute(
        statement,
        {
            "download_id": download_id,
            "user_id": user_id,
            "dataset_id": dataset_id,
            "format": fmt.value,
            "size": size,
            "requested_at": now,
        },
    )
    return DownloadRecord(
        download_id=download_id,
        user_id=user_id,
        dataset_id=dataset_id,
        format=fmt.value,
        size=size,
        requested_at=now,
    )


def build_download_event(record: DownloadRecord) -> dict[str, Any]:
    """Собрать payload ``commerce.downloads``."""
    event = DownloadEventPayload(
        eventId=f"ev_{record.download_id}",
        userId=record.user_id,
        at=record.requested_at,
        downloadId=record.download_id,
        datasetId=record.dataset_id,
        format=record.format,
    )
    return event.model_dump(mode="json")


async def publish_download(publisher: DownloadPublisher, record: DownloadRecord) -> None:
    """Опубликовать событие скачивания."""
    await publisher.publish(
        CommerceTopic.DOWNLOADS.value, build_download_event(record), record.download_id
    )


__all__ = [
    "STATUS_DONE",
    "DownloadPublisher",
    "DownloadRecord",
    "NullDownloadPublisher",
    "build_download_event",
    "publish_download",
    "record_download",
]
