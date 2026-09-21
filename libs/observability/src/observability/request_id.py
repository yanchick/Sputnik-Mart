"""Сквозной ``X-Request-Id``: контекст и ASGI-middleware.

Заголовок ``X-Request-Id`` генерируется при отсутствии и прокидывается сквозь все
сервисы через :mod:`contextvars`, а также возвращается в ответе.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_PATTERN = "req_{token}"

_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)

Message = MutableMapping[str, Any]
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def generate_request_id() -> str:
    """Сгенерировать новый идентификатор запроса вида ``req_...``."""
    return _REQUEST_ID_PATTERN.format(token=uuid.uuid4().hex[:12])


def get_request_id() -> str | None:
    """Вернуть текущий ``requestId`` из контекста или ``None``."""
    return _REQUEST_ID.get()


def set_request_id(request_id: str) -> Token[str | None]:
    """Установить ``requestId`` в контекст и вернуть токен сброса."""
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Восстановить предыдущее значение ``requestId`` по токену."""
    _REQUEST_ID.reset(token)


@contextmanager
def request_id_context(request_id: str | None = None) -> Iterator[str]:
    """Контекстный менеджер, гарантирующий наличие ``requestId`` внутри блока."""
    resolved = request_id or generate_request_id()
    token = set_request_id(resolved)
    try:
        yield resolved
    finally:
        reset_request_id(token)


def _extract_request_id(scope: Scope) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for raw_name, raw_value in headers:
        if raw_name.decode("latin-1").lower() == REQUEST_ID_HEADER.lower():
            value = raw_value.decode("latin-1").strip()
            return value or None
    return None


def _with_response_header(message: Message, request_id: str) -> Message:
    if message.get("type") != "http.response.start":
        return message
    raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
    header_name = REQUEST_ID_HEADER.lower().encode("latin-1")
    if not any(name.lower() == header_name for name, _ in raw_headers):
        raw_headers.append((header_name, request_id.encode("latin-1")))
    return {**message, "headers": raw_headers}


class RequestIdMiddleware:
    """Чистый ASGI-middleware сквозного ``X-Request-Id``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope) or generate_request_id()
        token = set_request_id(request_id)

        async def send_with_header(message: Message) -> None:
            await send(_with_response_header(message, request_id))

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            reset_request_id(token)


def propagate_request_id(headers: Mapping[str, str]) -> str:
    """Получить или сгенерировать ``requestId`` из заголовков исходящего вызова."""
    existing = headers.get(REQUEST_ID_HEADER)
    return existing or get_request_id() or generate_request_id()


def request_id_headers(
    *,
    request_id: str | None = None,
    traceparent: str | None = None,
) -> dict[str, str]:
    """Собрать заголовки сквозной корреляции для исходящего вызова.

    Возвращает ``X-Request-Id`` и, при наличии, W3C ``traceparent``, чтобы
    связать журналы и трейсы нескольких сервисов по одному запросу (FR-027).
    """
    headers = {REQUEST_ID_HEADER: request_id or get_request_id() or generate_request_id()}
    if traceparent:
        headers["traceparent"] = traceparent
    return headers


__all__ = [
    "REQUEST_ID_HEADER",
    "ASGIApp",
    "RequestIdMiddleware",
    "generate_request_id",
    "get_request_id",
    "propagate_request_id",
    "request_id_context",
    "request_id_headers",
    "reset_request_id",
    "set_request_id",
]
