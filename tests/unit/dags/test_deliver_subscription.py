"""Unit-тест отбора свежих чтений DAG ``deliver_subscription`` (T135, T146)."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

DAG_PATH = Path(__file__).resolve().parents[3] / "dags" / "deliver_subscription.py"


def _load_dag_module() -> ModuleType:
    sys.path.insert(0, str(DAG_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location("deliver_subscription", DAG_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(DAG_PATH.parent))


DAG_MODULE = _load_dag_module()


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    return getattr(DAG_MODULE, name)(*args, **kwargs)


def _subscription(subscription_id: str, dataset_id: str, status: str) -> dict[str, str]:
    return {
        "subscription_id": subscription_id,
        "dataset_id": dataset_id,
        "status": status,
    }


def test_dag_file_is_valid_python() -> None:
    ast.parse(DAG_PATH.read_text(encoding="utf-8"))


def test_active_subscriptions_skip_paused_and_cancelled() -> None:
    subscriptions = [
        _subscription("sub_a", "ds_weather-stations", "SUB_ACTIVE"),
        _subscription("sub_p", "ds_air-quality", "SUB_PAUSED"),
        _subscription("sub_c", "ds_energy-consumption", "SUB_CANCELLED"),
    ]

    active = _call("active_subscriptions", subscriptions)

    assert [item["subscription_id"] for item in active] == ["sub_a"]


def test_select_fresh_readings_only_for_active_dataset() -> None:
    subscriptions = [
        _subscription("sub_a", "ds_weather-stations", "SUB_ACTIVE"),
        _subscription("sub_p", "ds_air-quality", "SUB_PAUSED"),
    ]
    readings = [
        {"readingId": "rd_w1", "datasetId": "ds_weather-stations", "value": 1.0},
        {"readingId": "rd_a1", "datasetId": "ds_air-quality", "value": 2.0},
    ]

    selected = _call("select_fresh_readings", subscriptions, readings)

    assert [item["readingId"] for item in selected] == ["rd_w1"]
    assert selected[0]["subscriptionId"] == "sub_a"


def test_select_fresh_readings_is_idempotent_on_redelivery() -> None:
    subscriptions = [_subscription("sub_a", "ds_weather-stations", "SUB_ACTIVE")]
    readings = [
        {"readingId": "rd_w1", "datasetId": "ds_weather-stations", "value": 1.0},
        {"readingId": "rd_w2", "datasetId": "ds_weather-stations", "value": 2.0},
    ]

    first = _call("select_fresh_readings", subscriptions, readings)
    repeated = _call(
        "select_fresh_readings",
        subscriptions,
        readings,
        delivered_ids={"rd_w1", "rd_w2"},
    )

    assert len(first) == 2
    assert repeated == []


def test_select_fresh_readings_empty_input() -> None:
    assert _call("select_fresh_readings", [], []) == []
