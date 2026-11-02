"""Регрессия: сервисы compose не должны делить один host-порт.

Причина бага: ``api-gateway`` и ``web-vitrina`` публиковали ``8000:8000``.
Из-за конфликта host-порта ``api-gateway`` не поднимался, Panel не могла
разрезолвить ``http://api-gateway:8000`` и вход завершался ошибкой
``[Errno -2] Name or service not known``.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


_COMPOSE_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _resolve_compose_vars(spec: str) -> str:
    """Раскрыть `${VAR:-default}` в port-маппинге без запуска docker compose."""

    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2) or ""
        return os.environ.get(name, default)

    return _COMPOSE_VAR.sub(replace, spec)


def _expand_host_ports(host_spec: str) -> list[str]:
    """Разворачивает host-часть маппинга в список портов, включая диапазоны."""
    first, _, last = host_spec.partition("-")
    start = int(first)
    end = int(last) if last else start
    return [str(port) for port in range(start, end + 1)]


def _host_ports(mapping: Any) -> list[str]:
    """Извлекает published (host) порты из одного элемента ``service.ports``.

    Понимает короткий синтаксис (``"8050:8000"``), целые числа (порт без
    host-биндинга) и длинную форму (``dict`` с ключом ``published``).
    """
    if isinstance(mapping, dict):
        published = mapping.get("published")
        if published is None:
            return []
        return _expand_host_ports(str(published).split("/", maxsplit=1)[0])

    if isinstance(mapping, int):
        # Порт без host-биндинга — наружу ничего не публикуется.
        return []

    if not isinstance(mapping, str):
        raise TypeError(f"Неизвестный формат port mapping: {mapping!r}")

    spec = _resolve_compose_vars(mapping).split("/", maxsplit=1)[0]  # отбрасываем /tcp, /udp
    parts = spec.split(":")
    if len(parts) == 1:
        # "<container>" — host-порт не задан.
        return []
    return _expand_host_ports(parts[-2])


def _container_ports(mapping: Any) -> list[str]:
    """Извлекает container-порты из одного элемента ``service.ports``.

    Понимает короткий синтаксис (``"8050:8050"``), целые числа (порт без
    host-биндинга) и длинную форму (``dict`` с ключом ``target``).
    """
    if isinstance(mapping, dict):
        target = mapping.get("target")
        if target is None:
            return []
        return [str(target).split("/", maxsplit=1)[0]]

    if isinstance(mapping, int):
        return [str(mapping)]

    if not isinstance(mapping, str):
        raise TypeError(f"Неизвестный формат port mapping: {mapping!r}")

    spec = _resolve_compose_vars(mapping).split("/", maxsplit=1)[0]  # отбрасываем /tcp, /udp
    return [spec.split(":")[-1]]


def _host_ports_by_service(compose: dict[str, Any]) -> dict[str, list[str]]:
    """Возвращает ``{service: [host-порты]}`` для всех сервисов compose-файла."""
    services = compose.get("services") or {}
    ports_by_service: dict[str, list[str]] = {}
    for name, service in services.items():
        raw_ports = service.get("ports") or []
        ports = [port for mapping in raw_ports for port in _host_ports(mapping)]
        if ports:
            ports_by_service[name] = ports
    return ports_by_service


def test_no_two_services_publish_same_host_port() -> None:
    """Host-сторона каждого маппинга уникальна по всему compose-файлу."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    ports_by_service = _host_ports_by_service(compose)

    owners: dict[str, list[str]] = defaultdict(list)
    for service, ports in ports_by_service.items():
        for port in ports:
            owners[port].append(service)

    conflicts = {port: services for port, services in owners.items() if len(services) > 1}
    report = ", ".join(
        f"{port} -> {sorted(services)}" for port, services in sorted(conflicts.items())
    )
    assert not conflicts, f"Host-порты дублируются между сервисами: {report}"


def test_web_vitrina_host_container_and_service_port_agree() -> None:
    """Host-порт, container-порт и ``SERVICE_PORT`` web-vitrina совпадают.

    Иначе Bokeh выводит разрешённый WebSocket-origin из порта, на котором
    слушает, и браузер (host-порт) получает отказ 403 при ``Origin``.
    """
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    service = compose["services"]["web-vitrina"]

    raw_ports = service.get("ports") or []
    host_ports = [port for mapping in raw_ports for port in _host_ports(mapping)]
    container_ports = [port for mapping in raw_ports for port in _container_ports(mapping)]
    service_port = str((service.get("environment") or {})["SERVICE_PORT"])

    assert host_ports == ["8050"], f"web-vitrina host-порты: {host_ports}"
    assert container_ports == ["8050"], f"web-vitrina container-порты: {container_ports}"
    assert service_port == "8050", f"web-vitrina SERVICE_PORT: {service_port}"
