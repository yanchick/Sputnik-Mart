"""E2E-тест идентичности результата при одинаковом ``seed`` (T162, FR-029, SC-003)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from sim.buyers import build_behavior, build_buyers
from sim.dirty import DirtyConfig, contaminate, contamination_digest
from sim.providers import build_catalog
from sim.sensors import generate_readings, readings_digest

pytestmark = pytest.mark.e2e


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def test_sensors_and_contamination_are_deterministic() -> None:
    config = DirtyConfig(missing=0.1, duplicate=0.1, outlier=0.1, broken=0.1)

    assert readings_digest(generate_readings(seed=7, periods=12)) == readings_digest(
        generate_readings(seed=7, periods=12)
    )
    dirty_first = contaminate(generate_readings(seed=7, periods=12), seed=7, config=config)
    dirty_second = contaminate(generate_readings(seed=7, periods=12), seed=7, config=config)
    assert contamination_digest(dirty_first) == contamination_digest(dirty_second)


def test_catalog_and_buyers_are_deterministic_by_seed() -> None:
    assert _digest(build_catalog(seed=11)) == _digest(build_catalog(seed=11))
    assert _digest(build_buyers(seed=11)) == _digest(build_buyers(seed=11))
    assert _digest(build_behavior(seed=11)) == _digest(build_behavior(seed=11))
    # Иной seed даёт иной каталог (цены/качество генерируются детерминированно).
    assert _digest(build_catalog(seed=11)) != _digest(build_catalog(seed=12))
