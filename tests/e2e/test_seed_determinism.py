"""E2E-тест детерминизма генераторов по ``seed`` (T133, FR-029)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.cli import main as sim_main
from sim.dirty import DirtyConfig, contaminate, contamination_digest
from sim.sensors import generate_readings, readings_digest

pytestmark = pytest.mark.e2e


def test_sensors_same_seed_identical_and_other_seed_differs() -> None:
    first = generate_readings(seed=42, periods=8)
    second = generate_readings(seed=42, periods=8)
    third = generate_readings(seed=7, periods=8)
    assert readings_digest(first) == readings_digest(second)
    assert readings_digest(first) != readings_digest(third)
    assert len(first) == len(second) > 0


def test_dirty_same_seed_identical() -> None:
    readings = generate_readings(seed=42, periods=6)
    config = DirtyConfig(missing=0.2, duplicate=0.2, outlier=0.1, broken=0.1)
    first = contaminate(readings, seed=42, config=config)
    second = contaminate(readings, seed=42, config=config)
    assert contamination_digest(first) == contamination_digest(second)
    assert contamination_digest(first) != contamination_digest(readings)


def test_cli_sensors_output_is_deterministic(tmp_path: Path) -> None:
    first_path = tmp_path / "first.ndjson"
    second_path = tmp_path / "second.ndjson"
    assert sim_main(["sensors", "--seed", "42", "--periods", "5", "--out", str(first_path)]) == 0
    assert sim_main(["sensors", "--seed", "42", "--periods", "5", "--out", str(second_path)]) == 0
    assert first_path.read_bytes() == second_path.read_bytes()
    records = [json.loads(line) for line in first_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["stationId"].startswith("st_")


def test_empty_generation_is_safe() -> None:
    assert generate_readings(periods=0) == []
    assert contaminate([], seed=1) == []
