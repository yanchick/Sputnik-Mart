"""Интеграционный тест срабатывания алерта при деградации (T164, FR-026, SC-011)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from prometheus_client import REGISTRY

from quality.metrics import evaluate_degradation_alerts, publish_quality

pytestmark = pytest.mark.integration

ALERT_RULE = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "grafana"
    / "provisioning"
    / "alerting"
    / "degradation.yml"
)


def test_alert_evaluates_only_degraded_datasets() -> None:
    alerts = evaluate_degradation_alerts(
        [
            {"dataset_id": "ds_clean", "quality_score": 0.95},
            {"dataset_id": "ds_dirty", "quality_score": 0.30},
        ],
        baseline=0.9,
    )
    active = {alert.dataset for alert in alerts if alert.active}
    assert active == {"ds_dirty"}


def test_degradation_metric_is_published_and_alert_rule_targets_it() -> None:
    publish_quality("ds_degraded", 0.4, baseline=0.9)

    metric = REGISTRY.get_sample_value(
        "sputnik_quality_degradation_ratio", {"dataset": "ds_degraded"}
    )
    assert metric is not None and metric > 0.15

    assert ALERT_RULE.is_file(), "Grafana alert rule degradation.yml отсутствует"
    document = yaml.safe_load(ALERT_RULE.read_text(encoding="utf-8"))
    text = yaml.safe_dump(document, allow_unicode=True)
    assert "sputnik_quality_degradation_ratio" in text
