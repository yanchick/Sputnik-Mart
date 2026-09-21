"""Интеграционный тест bronze → silver → gold (T107)."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from typing import Any

import pyarrow.parquet as pq
import pytest

from ingestion.consumer import IngestionService, InMemoryDeduplicator, MinioBronzeSink
from ingestion.dlq import InMemoryDlq
from sensor_gateway.service import ReadingProcessor
from sim.sensors import build_stations, generate_readings
from transform.gold_quality import build_quality_rows, load_quality_mart
from transform.gold_readings import build_fact_rows, load_gold_readings
from validation.main import run_validation

pytestmark = pytest.mark.integration

DT = datetime(2026, 9, 1, tzinfo=UTC)
STATION = "st_meteo-01"


async def _pipeline(store: Any, clickhouse: Any) -> int:
    processor = ReadingProcessor(clock=lambda: DT)
    result = processor.ingest(generate_readings(seed=42, periods=4, stations=build_stations()[:1]))
    assert len(result.accepted) == 4

    service = IngestionService(
        MinioBronzeSink(store, "lake"), InMemoryDlq(), InMemoryDeduplicator()
    )
    for reading in result.accepted:
        outcome = await service.process_message(reading.model_dump(mode="json"))
        assert outcome.written == 1

    records = [reading.model_dump(mode="json") for reading in result.accepted]
    batch, keys, reports = await run_validation(records, store=store, bucket="lake", dt=DT.date())
    assert not batch.frame.empty
    assert "ds_weather-stations" in keys
    assert reports["ds_weather-stations"]["quality_score"] == pytest.approx(1.0, abs=0.2)

    silver_keys = await store.list_keys("lake", "silver/ds_weather-stations/")
    assert silver_keys
    body = await store.get_bytes("lake", silver_keys[-1])
    frame = pq.read_table(io.BytesIO(body)).to_pandas()
    assert len(frame) == 4

    rows = build_fact_rows(frame)
    loaded = await load_gold_readings(clickhouse, rows, DT.date())
    # Идемпотентность: повторная загрузка не создаёт дублей.
    assert await load_gold_readings(clickhouse, rows, DT.date()) == 0

    quality_rows = build_quality_rows(reports)
    assert await load_quality_mart(clickhouse, quality_rows) == len(quality_rows)
    # Повторный upsert заменяет строку, а не добавляет дубль.
    await load_quality_mart(clickhouse, quality_rows)
    quality_count = await clickhouse.execute(
        "SELECT count() FROM mart_quality_daily WHERE dataset_id = {dataset:String}",
        {"dataset": "ds_weather-stations"},
    )
    assert int(quality_count.result_rows[0][0]) == 1

    # fact_readings наполняет часовую витрину через Materialized View.
    hourly = await clickhouse.execute(
        "SELECT count() FROM mv_readings_hourly WHERE station_id = {station:String}",
        {"station": STATION},
    )
    assert int(hourly.result_rows[0][0]) >= 1
    return loaded


async def _count(clickhouse: Any) -> int:
    count = await clickhouse.execute(
        "SELECT count() FROM fact_readings WHERE station_id = {station:String}",
        {"station": STATION},
    )
    return int(count.result_rows[0][0])


def test_bronze_silver_gold_pipeline(minio_store: Any, clickhouse_client: Any) -> None:
    first_load = asyncio.run(_pipeline(minio_store, clickhouse_client))
    assert first_load == 0 or first_load == 4
    assert asyncio.run(_count(clickhouse_client)) == 4


def test_rerun_does_not_duplicate(minio_store: Any, clickhouse_client: Any) -> None:
    asyncio.run(_pipeline(minio_store, clickhouse_client))
    assert asyncio.run(_count(clickhouse_client)) == 4
