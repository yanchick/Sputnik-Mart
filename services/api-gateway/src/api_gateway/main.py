"""FastAPI api-gateway: маршрутизация, auth, rate-limit и Swagger (T088)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

from config import Settings, get_settings
from observability import (
    ApiError,
    configure_logging,
    get_logger,
    install_exception_handlers,
    user_id_from_headers,
)

from .auth import is_machine_path, is_public, resolve_principal
from .middleware import GatewayMiddleware, forward_headers
from .openapi import load_gateway_openapi
from .pagination import normalize_json_content
from .rate_limit import (
    STREAM_PREFIX,
    RateLimiter,
    create_rate_limiter,
    scoped_rate_limit_key,
)

_log = get_logger(__name__)

API_PREFIX = "/api/v1"
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_DEFAULT_URLS = {
    "identity": "http://localhost:8002",
    "catalog": "http://localhost:8001",
    "order": "http://localhost:8003",
    "review": "http://localhost:8004",
    "delivery": "http://localhost:8005",
    "quality": "http://localhost:8007",
}


def service_urls() -> dict[str, str]:
    """Адреса upstream-сервисов из окружения compose."""
    return {
        name: os.environ.get(f"SERVICE_URL_{name.upper()}", default)
        for name, default in _DEFAULT_URLS.items()
    }


def upstream_for(path: str, urls: Mapping[str, str]) -> str:
    """Выбрать upstream-сервис по пути запроса."""
    if path.startswith("/api/v1/auth") or path.startswith("/api/v1/users"):
        return urls["identity"]
    if (
        path.startswith("/api/v1/orders")
        or path.startswith("/api/v1/subscriptions")
        or path.startswith("/api/v1/downloads")
    ):
        return urls["order"]
    if path.startswith("/api/v1/streams"):
        return urls["delivery"]
    if path.startswith("/api/v1/reviews"):
        return urls["review"]
    if path.startswith("/api/v1/quality"):
        return urls["quality"]
    if path.startswith("/api/v1/datasets"):
        segments = path[len("/api/v1/datasets") :].strip("/").split("/")
        if segments and segments[-1] == "download":
            return urls["delivery"]
        if segments and segments[-1] == "rating":
            return urls["review"]
        return urls["catalog"]
    return urls["catalog"]


_PASSTHROUGH_HEADERS = frozenset({"content-type", "content-disposition"})
_PASSTHROUGH_PREFIXES = ("retry-after", "x-ratelimit-")


def _response_headers(upstream: httpx.Response) -> dict[str, str]:
    """Пробросить клиенту заголовки тела, выгрузки и лимитов (QR-6)."""
    return {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() in _PASSTHROUGH_HEADERS or name.lower().startswith(_PASSTHROUGH_PREFIXES)
    }


async def _proxy_stream(upstream: httpx.Response) -> AsyncIterator[bytes]:
    """Проксировать SSE чанками, не буферизуя бесконечный поток."""
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()


def create_app(
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    limiter: RateLimiter | None = None,
) -> FastAPI:
    """Собрать gateway с внедряемыми HTTP-клиентом и лимитером."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — API Gateway", version="1.0.0")
    app.add_middleware(GatewayMiddleware)
    install_exception_handlers(app)

    app.state.settings = resolved
    app.state.urls = service_urls()
    app.state.client = client or httpx.AsyncClient(timeout=30.0)
    app.state.limiter = limiter or create_rate_limiter(os.environ.get("REDIS_URL"))

    contract_dir = Path(os.environ.get("CONTRACTS_DIR", "specs/001-sputnik-data-portal/contracts"))
    if contract_dir.is_dir():
        spec = load_gateway_openapi(contract_dir)
        app.openapi = lambda: spec  # type: ignore[method-assign]

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "api-gateway"}

    @app.api_route(f"{API_PREFIX}/{{full_path:path}}", methods=_PROXY_METHODS)
    async def proxy(full_path: str, request: Request) -> Response:
        path = f"{API_PREFIX}/{full_path}"
        principal_user: str | None = None
        rate_headers: dict[str, str] = {}

        if not is_public(path, request.method):
            principal = resolve_principal(request, request.app.state.settings.app.auth_secret)
            if principal is None:
                raise ApiError(401, "UNAUTHORIZED", "Требуется аутентификация")
            if principal.kind == "machine" and not is_machine_path(path):
                raise ApiError(401, "UNAUTHORIZED", "X-Api-Key допустим только для download/stream")
            limit = request.app.state.settings.app.rate_limit_per_minute
            window = request.app.state.settings.app.rate_limit_window_seconds
            scoped_key = scoped_rate_limit_key(principal.rate_limit_key, path)
            result = await request.app.state.limiter.check(scoped_key, limit, window)
            rate_headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(result.remaining),
                "X-RateLimit-Reset": str(result.reset_after),
            }
            if not result.allowed:
                raise ApiError(
                    429,
                    "RATE_LIMITED",
                    f"Лимит превышен, повтор через {result.retry_after} с",
                    headers={**rate_headers, "Retry-After": str(result.retry_after)},
                )
            principal_user = principal.user_id
        else:
            # Публичный вход может прийти с Bearer — прокинуть пользователя дальше.
            principal_user = user_id_from_headers(
                request.headers.get("Authorization"),
                None,
                request.app.state.settings.app.auth_secret,
            )

        target = upstream_for(path, request.app.state.urls)
        url = f"{target.rstrip('/')}{path}"
        headers = forward_headers(
            dict(request.headers),
            user_id=principal_user,
            request_id=request.headers.get("X-Request-Id"),
        )
        body = await request.body()
        upstream_request = request.app.state.client.build_request(
            request.method,
            url,
            params=list(request.query_params.multi_items()),
            content=body,
            headers=headers,
        )
        upstream = await request.app.state.client.send(upstream_request, stream=True)
        response_headers = {**_response_headers(upstream), **rate_headers}
        if path.startswith(STREAM_PREFIX):
            return StreamingResponse(
                _proxy_stream(upstream),
                status_code=upstream.status_code,
                headers=response_headers,
            )
        try:
            content = await upstream.aread()
        finally:
            await upstream.aclose()
        content = normalize_json_content(content, response_headers.get("content-type"))
        return Response(
            content=content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    return app


def main() -> None:
    """Запустить gateway под uvicorn."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="api-gateway")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "create_app", "main", "service_urls", "upstream_for"]
