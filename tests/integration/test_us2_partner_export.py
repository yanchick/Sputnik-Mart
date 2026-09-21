"""Интеграционный тест партнёрской выгрузки (CSV поставщика) (T110, FR-033)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from validation.main import run_validation
from validation.partner import parse_partner_csv

pytestmark = pytest.mark.integration

CSV_CONTENT = (
    "stationId,metric,value,measuredAt,unit\n"
    "st_partner-01,TEMPERATURE,12.5,2026-09-04T00:00:00+00:00,C\n"
    "st_partner-01,TEMPERATURE,13.5,2026-09-04T01:00:00+00:00,C\n"
)


async def _flow(store: Any) -> None:
    readings = parse_partner_csv(CSV_CONTENT, "pv_partner")
    assert len(readings) == 2
    assert readings[0]["readingId"].startswith("rd_partner_pv_partner_")

    _batch, keys, reports = await run_validation(
        readings, store=store, bucket="lake", dt=date(2026, 9, 4)
    )
    assert keys.get("ds_weather-stations")
    assert "ds_weather-stations" in reports

    object_keys = await store.list_keys("lake", "silver/ds_weather-stations/")
    assert any("2026-09-04" in key for key in object_keys)

    malformed = "stationId,value\nst_1,5\n"
    assert parse_partner_csv(malformed, "pv_partner") == []
    _empty_batch, empty_keys, empty_reports = await run_validation(
        [], store=store, bucket="lake", dt=date(2026, 9, 5)
    )
    assert empty_keys == {}
    assert empty_reports == {}


def test_partner_csv_flows_through_validation(minio_store: Any) -> None:
    asyncio.run(_flow(minio_store))
