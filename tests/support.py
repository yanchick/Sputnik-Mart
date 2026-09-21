"""Общие хелперы тестов US1: сборка приложений и клиентов."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from api_gateway.main import create_app as create_gateway_app
from api_gateway.rate_limit import InMemoryRateLimiter
from catalog.clicks import NullClickPublisher
from catalog.main import create_app as create_catalog_app
from delivery.idempotency import InMemoryReadingDeduplicator, ReadingDeduplicator
from delivery.main import create_app as create_delivery_app
from delivery.streams import ReadingSource, StaticReadingSource
from fastapi import FastAPI
from identity.main import create_app as create_identity_app
from order.events import NullPublisher
from order.main import create_app as create_order_app
from review.events import NullReviewPublisher
from review.main import create_app as create_review_app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from service_client import HttpServiceClient

SERVICE_PORTS = {
    8001: "catalog",
    8002: "identity",
    8003: "order",
    8004: "review",
    8005: "delivery",
}

DEMO_EMAIL = "buyer@sputnik.demo"
DEMO_PASSWORD = "demo"
DEMO_DATASET = "ds_weather-stations"
CONTRACT_DIR = (
    Path(__file__).resolve().parents[1] / "specs" / "001-sputnik-data-portal" / "contracts"
)


def load_openapi(filename: str) -> Any:
    """Загрузить OpenAPI-контракт в schemathesis без привязки к app.

    Проверка ``Allow`` для OPTIONS отключена: контракты описывают только
    бизнес-методы, а negative-фаззинг методов порождает OPTIONS/405.
    """
    from schemathesis.openapi import from_dict

    document = yaml.safe_load((CONTRACT_DIR / filename).read_text(encoding="utf-8"))
    loaded = from_dict(document)
    loaded.config.checks.allow_header_conformance.enabled = False
    return loaded


@dataclass
class Apps:
    """Набор US1-сервисов и gateway, разделяющих одну БД."""

    identity: FastAPI
    catalog: FastAPI
    order: FastAPI
    review: FastAPI
    delivery: FastAPI
    gateway: FastAPI
    order_events: NullPublisher
    review_events: NullReviewPublisher
    catalog_events: NullClickPublisher
    delivery_reading_source: ReadingSource
    delivery_deduplicator: ReadingDeduplicator
    gateway_client: httpx.AsyncClient
    peer_client: httpx.AsyncClient


def build_apps(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings | None = None,
    *,
    reading_source: ReadingSource | None = None,
    deduplicator: ReadingDeduplicator | None = None,
) -> Apps:
    """Собрать приложения US1–US3 поверх общей фабрики сессий."""
    resolved = settings or Settings()
    order_events = NullPublisher()
    review_events = NullReviewPublisher()
    catalog_events = NullClickPublisher()
    source = reading_source or StaticReadingSource(demo_stream_readings())
    dedup = deduplicator or InMemoryReadingDeduplicator()

    peer_registry: dict[int, FastAPI] = {}

    async def peer_handler(request: httpx.Request) -> httpx.Response:
        port = request.url.port
        app = peer_registry.get(port) if port is not None else None
        if app is None:
            return httpx.Response(502, json={"error": {"code": "BAD_GATEWAY"}})
        transport = httpx.ASGITransport(app=app)
        return await transport.handle_async_request(request)

    peer_client = httpx.AsyncClient(transport=httpx.MockTransport(peer_handler))

    def peer(name: str) -> HttpServiceClient:
        return HttpServiceClient(name, client=peer_client)

    identity = create_identity_app(
        settings=resolved, session_factory=session_factory, order_client=peer("order")
    )
    catalog = create_catalog_app(
        settings=resolved,
        session_factory=session_factory,
        events=catalog_events,
        identity_client=peer("identity"),
    )
    order = create_order_app(
        settings=resolved,
        session_factory=session_factory,
        events=order_events,
        catalog_client=peer("catalog"),
    )
    review = create_review_app(
        settings=resolved, session_factory=session_factory, events=review_events
    )
    delivery = create_delivery_app(
        settings=resolved,
        session_factory=session_factory,
        reading_source=source,
        deduplicator=dedup,
        order_client=peer("order"),
        identity_client=peer("identity"),
        catalog_client=peer("catalog"),
        ping_interval=0.05,
    )
    gateway = create_gateway_app(
        settings=resolved,
        client=_gateway_http_client(catalog, identity, order, review, delivery),
        limiter=InMemoryRateLimiter(),
    )
    peer_registry.update(
        {
            8001: catalog,
            8002: identity,
            8003: order,
            8004: review,
            8005: delivery,
        }
    )
    return Apps(
        identity=identity,
        catalog=catalog,
        order=order,
        review=review,
        delivery=delivery,
        gateway=gateway,
        order_events=order_events,
        review_events=review_events,
        catalog_events=catalog_events,
        delivery_reading_source=source,
        delivery_deduplicator=dedup,
        gateway_client=_client(gateway),
        peer_client=peer_client,
    )


def demo_stream_readings() -> list[dict[str, Any]]:
    """Детерминированные чтения для живого потока в тестах."""
    base = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        {
            "readingId": f"rd_stream_{index}",
            "stationId": "st_meteo-01",
            "datasetId": DEMO_DATASET,
            "metric": "TEMPERATURE",
            "value": 10.0 + index,
            "unit": "C",
            "measuredAt": (base.replace(hour=index)).isoformat(),
        }
        for index in range(3)
    ]


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Разобрать тело ``text/event-stream`` в список кадров."""
    events: list[dict[str, Any]] = []
    event: str | None = None
    event_id: str | None = None
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("id:"):
            event_id = line[len("id:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif not line.strip() and event is not None:
            payload = "".join(data_lines) or "{}"
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {}
            events.append({"event": event, "id": event_id, "data": data})
            event, event_id, data_lines = None, None, []
    return events


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _gateway_http_client(*services: FastAPI) -> httpx.AsyncClient:
    by_port = dict(zip(SERVICE_PORTS, services, strict=True))

    async def handler(request: httpx.Request) -> httpx.Response:
        port = request.url.port
        if port is None or port not in by_port:
            return httpx.Response(502, json={"error": {"code": "BAD_GATEWAY"}})
        transport = httpx.ASGITransport(app=by_port[port])
        return await transport.handle_async_request(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def client_for(app: FastAPI) -> httpx.AsyncClient:
    """Async-клиент к сервису через ASGI-транспорт."""
    return _client(app)


async def login(client: httpx.AsyncClient, email: str = DEMO_EMAIL) -> str:
    """Войти демо-аккаунтом и вернуть Bearer-токен."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["accessToken"]
    return token


async def token_for(apps: Apps, email: str = DEMO_EMAIL) -> str:
    """Получить Bearer-токен через identity-сервис, чтобы звать другие сервисы."""
    async with client_for(apps.identity) as client:
        return await login(client, email)


def auth_header(token: str) -> dict[str, str]:
    """Заголовок Bearer."""
    return {"Authorization": f"Bearer {token}"}


def paged_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Извлечь ``data`` из пагинированного ответа."""
    return list(body["data"])


class FakeAddSession:
    """Мини-сессия для unit-тестов путей, где нужны только ``add``/``flush``."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        """Запомнить добавляемый ORM-объект."""
        self.added.append(obj)

    async def flush(self) -> None:
        """Имитация flush без обращения к БД."""
        return None


__all__ = [
    "DEMO_DATASET",
    "DEMO_EMAIL",
    "DEMO_PASSWORD",
    "SERVICE_PORTS",
    "Apps",
    "FakeAddSession",
    "auth_header",
    "build_apps",
    "client_for",
    "demo_stream_readings",
    "login",
    "paged_items",
    "parse_sse",
    "token_for",
]
