"""Единый конверт ошибок ``{error:{code,message,requestId,details}}`` (FR-034).

Обработчики FastAPI приводят любые исключения сервисов и api-gateway к одному
формату с сквозным ``requestId``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger
from .request_id import get_request_id

_log = get_logger(__name__)

DEFAULT_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


class ApiError(Exception):
    """Ошибка API, сериализуемая в единый конверт ``{error:...}``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Iterable[Mapping[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = code
        self.message = message
        self.details: list[dict[str, Any]] = [dict(item) for item in details or []]
        self.headers = dict(headers or {})


def error_payload(
    code: str,
    message: str,
    *,
    details: Iterable[Mapping[str, Any]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Собрать тело ответа ``{error:{code,message,requestId,details}}``."""
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "requestId": request_id or get_request_id() or "",
        "details": [dict(item) for item in details or []],
    }
    return {"error": body}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Iterable[Mapping[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Сформировать ``JSONResponse`` с единым конвертом ошибки."""
    return JSONResponse(
        status_code=status_code,
        content=error_payload(code, message, details=details),
        headers=dict(headers or {}),
    )


def _validation_details(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in errors:
        location = ".".join(str(part) for part in error.get("loc", ()))
        details.append(
            {
                "field": location,
                "message": str(error.get("msg", "")),
                "code": str(error.get("type", "INVALID")),
            }
        )
    return details


def install_exception_handlers(app: FastAPI) -> None:
    """Зарегистрировать обработчики исключений с единым конвертом ошибок."""

    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            exc.status_code, exc.code, exc.message, details=exc.details, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            400,
            "VALIDATION_ERROR",
            "Некорректный запрос",
            details=_validation_details(list(exc.errors())),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = DEFAULT_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else code
        return error_response(exc.status_code, code, message, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        _log.exception("unhandled_error", error=str(exc))
        return error_response(500, "INTERNAL_ERROR", "Внутренняя ошибка сервера")


__all__ = [
    "DEFAULT_ERROR_CODES",
    "ApiError",
    "error_payload",
    "error_response",
    "install_exception_handlers",
]
