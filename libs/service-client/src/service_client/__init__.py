"""Внутренние HTTP-вызовы между сервисами (M6, правило владения данными).

Каждый сервис — единственный владелец своих таблиц, поэтому чтение или запись
чужих данных выполняется только через API сервиса-владельца. Этот модуль —
единая точка исходящих межсервисных вызовов: он берёт адреса из
``SERVICE_URL_<NAME>`` (как api-gateway) и превращает ошибки апстрима в
единый конверт :class:`observability.ApiError`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from observability import ApiError

#: Порты локального запуска; совпадают с фолбэками api-gateway.
DEFAULT_PORTS: dict[str, int] = {
    "identity": 8002,
    "catalog": 8001,
    "order": 8003,
    "review": 8004,
    "delivery": 8005,
    "quality": 8007,
}


def service_url(service: str) -> str:
    """Базовый URL сервиса из ``SERVICE_URL_<NAME>`` или localhost-фолбэк."""
    default_port = DEFAULT_PORTS[service]
    return os.environ.get(f"SERVICE_URL_{service.upper()}", f"http://localhost:{default_port}")


def _error_from_response(response: httpx.Response) -> ApiError:
    """Собрать :class:`ApiError` из единого конверта ошибки апстрима."""
    code = "INTERNAL_ERROR"
    message = f"Ошибка сервиса ({response.status_code})"
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = str(error.get("code") or code)
        message = str(error.get("message") or message)
    return ApiError(response.status_code, code, message)


class ServiceClient(Protocol):
    """Минимальный контракт клиента к сервису-владельцу данных."""

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Выполнить ``GET`` и вернуть разобранный JSON."""
        ...

    async def post_json(
        self,
        path: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Выполнить ``POST`` и вернуть разобранный JSON."""
        ...


class HttpServiceClient:
    """Async HTTP-клиент к одному сервису с единой обработкой ошибок.

    Нижележащий ``httpx.AsyncClient`` создаётся лениво при первом запросе,
    поэтому приложение не держит соединение с сервисами, к которым не ходит.
    """

    def __init__(
        self,
        service: str,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.service = service
        self._base_url = (base_url or service_url(service)).rstrip("/")
        self._client = client
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        """Вернуть (создав при необходимости) нижележащий HTTP-клиент."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Выполнить запрос; ошибка апстрима поднимается как :class:`ApiError`."""
        try:
            response = await self._http().request(
                method,
                f"{self._base_url}{path}",
                params=params,
                headers=headers,
                json=json,
            )
        except httpx.HTTPError as error:
            raise ApiError(502, "BAD_GATEWAY", f"Сервис {self.service} недоступен") from error
        if response.status_code >= 400:
            raise _error_from_response(response)
        return response

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Выполнить ``GET`` и вернуть разобранный JSON."""
        response = await self.request("GET", path, params=params, headers=headers)
        return response.json()

    async def post_json(
        self,
        path: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Выполнить ``POST`` и вернуть разобранный JSON."""
        response = await self.request("POST", path, json=json, headers=headers)
        return response.json()

    async def aclose(self) -> None:
        """Закрыть нижележащий HTTP-клиент, если он был создан."""
        if self._client is not None:
            await self._client.aclose()


def forward_auth(headers: Mapping[str, str]) -> dict[str, str]:
    """Пробросить авторизационные заголовки вызывающего в вызов владельца."""
    forwarded: dict[str, str] = {}
    for name in ("Authorization", "X-Api-Key"):
        value = headers.get(name)
        if value:
            forwarded[name] = value
    return forwarded


async def resolve_api_key(identity: ServiceClient, api_key: str) -> str | None:
    """Разрешить машинный ключ в покупателя через identity-сервис (M6).

    Возвращает ``user_id`` или ``None``, если ключ неизвестен/отозван.
    """
    payload = await identity.post_json("/api/v1/api-keys/resolve", json={"apiKey": api_key})
    user_id = payload.get("userId") if isinstance(payload, dict) else None
    return str(user_id) if user_id else None


__all__ = [
    "DEFAULT_PORTS",
    "HttpServiceClient",
    "ServiceClient",
    "forward_auth",
    "resolve_api_key",
    "service_url",
]
