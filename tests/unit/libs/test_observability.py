"""Unit-тесты observability (T032)."""

from __future__ import annotations

import json

import pytest
from prometheus_client import REGISTRY

from observability import (
    RequestIdMiddleware,
    configure_logging,
    configure_tracing,
    current_trace_id,
    generate_request_id,
    get_logger,
    get_request_id,
    get_tracer,
    observe_request,
    render_metrics,
    request_id_context,
    set_consumer_lag,
    set_data_freshness,
    set_quality_score,
    span,
)
from observability.request_id import (
    REQUEST_ID_HEADER,
    Message,
    Receive,
    Scope,
    Send,
)

pytestmark = pytest.mark.unit

_HEADER_BYTES = REQUEST_ID_HEADER.lower().encode()


def test_generate_request_id_is_unique_and_prefixed() -> None:
    first = generate_request_id()
    second = generate_request_id()

    assert first.startswith("req_")
    assert first != second


def test_request_id_context_sets_and_resets() -> None:
    assert get_request_id() is None

    with request_id_context() as request_id:
        assert request_id.startswith("req_")
        assert get_request_id() == request_id

    assert get_request_id() is None


async def _receive() -> Message:
    return {"type": "http.request"}


def _collector(sent: list[Message]) -> Send:
    async def send(message: Message) -> None:
        sent.append(message)

    return send


async def _response_app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def test_request_id_middleware_propagates_incoming_header() -> None:
    sent: list[Message] = []
    middleware = RequestIdMiddleware(_response_app)
    scope: Scope = {"type": "http", "headers": [(_HEADER_BYTES, b"req_incoming")]}

    await middleware(scope, _receive, _collector(sent))

    assert sent[0]["type"] == "http.response.start"
    assert dict(sent[0]["headers"])[_HEADER_BYTES] == b"req_incoming"
    assert get_request_id() is None


async def test_request_id_middleware_generates_header_when_absent() -> None:
    sent: list[Message] = []
    middleware = RequestIdMiddleware(_response_app)

    await middleware({"type": "http"}, _receive, _collector(sent))

    header_value = dict(sent[0]["headers"])[_HEADER_BYTES]
    assert header_value.startswith(b"req_")


def test_metrics_render_and_record() -> None:
    observe_request("svc", "GET", "/datasets", 200, 0.01)
    set_consumer_lag("sensors.readings.v1", 0, 3.0)
    set_data_freshness("ds_x", -5.0)
    set_quality_score("ds_x", 1.4)

    rendered = render_metrics().decode("utf-8")
    assert "sputnik_http_requests_total" in rendered
    assert "sputnik_consumer_lag" in rendered

    assert (
        REGISTRY.get_sample_value(
            "sputnik_http_requests_total",
            {"service": "svc", "method": "GET", "route": "/datasets", "status": "200"},
        )
        == 1.0
    )
    assert REGISTRY.get_sample_value("sputnik_data_freshness_seconds", {"dataset": "ds_x"}) == 0.0
    assert REGISTRY.get_sample_value("sputnik_quality_score", {"dataset": "ds_x"}) == 1.0


def test_tracing_noop_without_sdk() -> None:
    configure_tracing("test-service")

    tracer = get_tracer("test")
    with span(tracer, "operation", attributes={"k": "v"}) as active:
        assert active is not None
    assert current_trace_id() is None


def test_structlog_json_contains_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    with request_id_context("req_logtest"):
        get_logger("test").info("hello", answer=42)

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert payload["event"] == "hello"
    assert payload["requestId"] == "req_logtest"
    assert payload["answer"] == 42
