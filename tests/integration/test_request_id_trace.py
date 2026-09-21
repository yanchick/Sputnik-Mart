"""Интеграционный тест сквозного ``requestId`` через несколько сервисов (T159, FR-027)."""

from __future__ import annotations

import pytest

from observability.request_id import REQUEST_ID_HEADER, request_id_headers
from support import DEMO_EMAIL, DEMO_PASSWORD, Apps, auth_header, client_for, token_for

pytestmark = pytest.mark.integration

REQUEST_ID = "req_trace_acceptance_1"


async def test_request_id_is_echoed_by_each_service(apps: Apps) -> None:
    headers = {REQUEST_ID_HEADER: REQUEST_ID}

    async with client_for(apps.identity) as identity_client:
        login = await identity_client.post(
            "/api/v1/auth/login",
            json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
            headers=headers,
        )
    assert login.status_code == 200
    assert login.headers[REQUEST_ID_HEADER] == REQUEST_ID

    token = await token_for(apps)
    async with client_for(apps.catalog) as catalog_client:
        listing = await catalog_client.get(
            "/api/v1/datasets", headers={**auth_header(token), **headers}
        )
    assert listing.status_code == 200
    assert listing.headers[REQUEST_ID_HEADER] == REQUEST_ID


async def test_request_id_survives_gateway_hop_and_error_envelope(apps: Apps) -> None:
    token = await token_for(apps)
    headers = {**auth_header(token), REQUEST_ID_HEADER: REQUEST_ID}

    proxied = await apps.gateway_client.get("/api/v1/datasets", headers=headers)
    assert proxied.status_code == 200
    assert proxied.headers[REQUEST_ID_HEADER] == REQUEST_ID

    unauthorized = await apps.gateway_client.get(
        "/api/v1/datasets", headers={REQUEST_ID_HEADER: REQUEST_ID}
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["requestId"] == REQUEST_ID


def test_outgoing_headers_include_request_id_and_traceparent() -> None:
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    headers = request_id_headers(request_id=REQUEST_ID, traceparent=traceparent)

    assert headers[REQUEST_ID_HEADER] == REQUEST_ID
    assert headers["traceparent"] == traceparent
