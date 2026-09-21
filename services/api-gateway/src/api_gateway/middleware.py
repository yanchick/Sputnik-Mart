"""Сквозной ``X-Request-Id`` и конверт ошибок gateway (T091)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any

from observability import error_response
from observability.request_id import RequestIdMiddleware, request_id_headers

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_HOP_BY_HOP = frozenset({"host", "content-length", "connection", "transfer-encoding"})


class GatewayMiddleware:
    """Обёртка gateway: request-id + гарантированный конверт ``{error:...}``."""

    def __init__(self, app: ASGIApp) -> None:
        self._request_id_app = RequestIdMiddleware(app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._request_id_app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._request_id_app(scope, receive, tracking_send)
        except Exception:
            if response_started:
                raise
            response = error_response(500, "INTERNAL_ERROR", "Внутренняя ошибка сервера")
            await response(scope, receive, send)


def forward_headers(
    request_headers: Mapping[str, str],
    *,
    user_id: str | None,
    request_id: str | None = None,
) -> dict[str, str]:
    """Подготовить заголовки для вызова upstream-сервиса."""
    headers = {
        name: value
        for name, value in request_headers.items()
        if name.lower() not in _HOP_BY_HOP and name.lower() != "x-user-id"
    }
    if user_id is not None:
        headers["X-User-Id"] = user_id
    headers.update(
        request_id_headers(
            request_id=request_id,
            traceparent=request_headers.get("traceparent"),
        )
    )
    return headers


__all__ = ["GatewayMiddleware", "forward_headers"]
