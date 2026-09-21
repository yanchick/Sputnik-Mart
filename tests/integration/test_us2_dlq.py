"""Интеграционный тест DLQ: 100% невалидных в DLQ, 0% в silver (T108)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from contracts import ContentTopic, DeadReadingReason
from ingestion.consumer import IngestionService, InMemoryDeduplicator, MinioBronzeSink
from ingestion.dlq import InMemoryDlq, MinioDlqArchive

pytestmark = pytest.mark.integration

DT = datetime(2026, 9, 1, tzinfo=UTC)


async def _dlq_flow(store: Any) -> None:
    before = await store.list_keys("lake", "bronze/")
    dlq = InMemoryDlq()
    service = IngestionService(MinioBronzeSink(store, "lake"), dlq, InMemoryDeduplicator())
    invalid = [{"readingId": f"rd_bad_{index}", "value": "not-a-number"} for index in range(5)]
    for message in invalid:
        await service.process_message(message)

    assert len(dlq.dead) == 5
    assert {item.reason for item in dlq.dead} == {DeadReadingReason.SCHEMA_MISMATCH}
    after = await store.list_keys("lake", "bronze/")
    assert len(after) == len(before), "битые записи не должны попадать в bronze"

    archive = MinioDlqArchive(store, "lake")
    await archive.archive(
        ContentTopic.DLQ.value, DT.date(), [item.model_dump(mode="json") for item in dlq.dead]
    )
    archived = await store.list_keys(
        "lake", f"dlq/{ContentTopic.DLQ.value}/{DT.date().isoformat()}/"
    )
    assert len(archived) == 1


def test_invalid_records_only_reach_dlq(minio_store: Any) -> None:
    asyncio.run(_dlq_flow(minio_store))
