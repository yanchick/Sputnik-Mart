"""Регрессия: compose использует доступный S3-образ с Docker Hub.

Официальные ``minio/minio`` и ``quay.io/minio/*`` удалены/закрыты для
анонимного pull в 2026. Хранилище озера должно тянуться с Docker Hub;
``pgsty/silo`` — поддерживаемый форк MinIO с тем же S3 API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

DEAD_PREFIXES = (
    "quay.io/minio/",
    "minio/minio",
    "minio/mc",
    "bitnami/minio:",
)


def _compose() -> dict[str, Any]:
    parsed: object = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise TypeError(
            f"docker-compose.yml: ожидался YAML-объект, получено {type(parsed).__name__}"
        )
    return parsed


def test_minio_service_uses_docker_hub_silo() -> None:
    image = _compose()["services"]["minio"]["image"]
    assert image.startswith(("pgsty/silo:", "docker.io/pgsty/silo:")), image


def test_minio_init_uses_docker_hub_mc() -> None:
    image = _compose()["services"]["minio-init"]["image"]
    assert image.startswith(("pgsty/mc:", "docker.io/pgsty/mc:")), image


def test_no_dead_minio_registry_references() -> None:
    services = _compose()["services"]
    for name in ("minio", "minio-init"):
        image = services[name]["image"]
        assert not image.startswith(DEAD_PREFIXES), f"{name}: мёртвый образ {image}"
