"""HTTP-клиент gateway на httpx для Panel-фасада (T098)."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_GATEWAY_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


class GatewayError(RuntimeError):
    """Ошибка ответа gateway с кодом и сообщением из конверта."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


class GatewayClient:
    """Тонкая синхронная обёртка над REST API gateway (единственная sync-поверхность)."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("GATEWAY_URL") or DEFAULT_GATEWAY_URL).rstrip(
            "/"
        )
        self._client = client or httpx.Client(base_url=self._base_url, timeout=30.0)
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        """Текущий Bearer-токен покупателя."""
        return self._token

    @property
    def gateway_url(self) -> str:
        """Базовый URL gateway (для SSE-клиента)."""
        return self._base_url

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        code = "HTTP_ERROR"
        message = response.text
        try:
            body: dict[str, Any] = response.json()
            error = body.get("error", {})
            code = str(error.get("code", code))
            message = str(error.get("message", message))
        except ValueError:
            pass
        raise GatewayError(response.status_code, code, message)

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Войти по демонстрационному аккаунту."""
        response = self._client.post(
            f"{API_PREFIX}/auth/login", json={"email": email, "password": password}
        )
        self._raise(response)
        payload: dict[str, Any] = response.json()
        self._token = str(payload["accessToken"])
        return payload

    def logout(self) -> None:
        """Сбросить локальный токен."""
        self._token = None

    def me(self) -> dict[str, Any]:
        """Профиль текущего покупателя."""
        response = self._client.get(f"{API_PREFIX}/users/me", headers=self._headers())
        self._raise(response)
        return dict(response.json())

    def list_datasets(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        min_quality: float | None = None,
    ) -> dict[str, Any]:
        """Постраничный список датасетов с фильтрами."""
        params: dict[str, Any] = {"page": page, "pageSize": page_size}
        if category:
            params["category"] = category
        if min_quality is not None:
            params["minQuality"] = min_quality
        response = self._client.get(
            f"{API_PREFIX}/datasets", params=params, headers=self._headers()
        )
        self._raise(response)
        return dict(response.json())

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Карточка датасета."""
        response = self._client.get(f"{API_PREFIX}/datasets/{dataset_id}", headers=self._headers())
        self._raise(response)
        return dict(response.json())

    def get_schema(self, dataset_id: str) -> list[dict[str, Any]]:
        """Схема полей датасета."""
        response = self._client.get(
            f"{API_PREFIX}/datasets/{dataset_id}/schema", headers=self._headers()
        )
        self._raise(response)
        return list(response.json())

    def get_sample(self, dataset_id: str, fmt: str = "CSV") -> str:
        """Образец датасета в выбранном формате."""
        response = self._client.get(
            f"{API_PREFIX}/datasets/{dataset_id}/sample",
            params={"format": fmt},
            headers=self._headers(),
        )
        self._raise(response)
        return response.text

    def create_order(self, dataset_id: str, idempotency_key: str | None = None) -> dict[str, Any]:
        """Создать заказ (покупку) с идемпотентностью."""
        response = self._client.post(
            f"{API_PREFIX}/orders",
            json={"datasetId": dataset_id},
            headers=self._headers(idempotency_key),
        )
        self._raise(response)
        return dict(response.json())

    def list_orders(self, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """Заказы покупателя."""
        response = self._client.get(
            f"{API_PREFIX}/orders",
            params={"page": page, "pageSize": page_size},
            headers=self._headers(),
        )
        self._raise(response)
        return dict(response.json())

    def list_downloads(self, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """История скачиваний покупателя."""
        response = self._client.get(
            f"{API_PREFIX}/downloads",
            params={"page": page, "pageSize": page_size},
            headers=self._headers(),
        )
        self._raise(response)
        return dict(response.json())

    def create_subscription(self, dataset_id: str, interval_sec: int) -> dict[str, Any]:
        """Оформить подписку на поток."""
        response = self._client.post(
            f"{API_PREFIX}/subscriptions",
            json={"datasetId": dataset_id, "intervalSec": interval_sec},
            headers=self._headers(),
        )
        self._raise(response)
        return dict(response.json())

    def list_subscriptions(self, user_id: str) -> dict[str, Any]:
        """Подписки покупателя."""
        response = self._client.get(
            f"{API_PREFIX}/users/{user_id}/subscriptions", headers=self._headers()
        )
        self._raise(response)
        return dict(response.json())

    def pause_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Приостановить подписку (``SUB_PAUSED``), сохранив купленные данные."""
        return self._change_subscription_state(subscription_id, "pause")

    def resume_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Возобновить подписку (``SUB_ACTIVE``) без дублей."""
        return self._change_subscription_state(subscription_id, "resume")

    def cancel_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Окончательно отменить подписку (``SUB_CANCELLED``)."""
        return self._change_subscription_state(subscription_id, "cancel")

    def _change_subscription_state(self, subscription_id: str, action: str) -> dict[str, Any]:
        response = self._client.post(
            f"{API_PREFIX}/subscriptions/{subscription_id}/{action}", headers=self._headers()
        )
        self._raise(response)
        return dict(response.json())

    def download(self, dataset_id: str, fmt: str = "CSV") -> bytes:
        """Скачать оплаченный датасет в выбранном формате."""
        response = self._client.get(
            f"{API_PREFIX}/datasets/{dataset_id}/download",
            params={"format": fmt},
            headers=self._headers(),
        )
        self._raise(response)
        return response.content

    def list_reviews(self, dataset_id: str) -> dict[str, Any]:
        """Отзывы датасета."""
        response = self._client.get(
            f"{API_PREFIX}/reviews",
            params={"datasetId": dataset_id},
            headers=self._headers(),
        )
        self._raise(response)
        return dict(response.json())

    def create_review(
        self, dataset_id: str, rating: int, text: str | None = None
    ) -> dict[str, Any]:
        """Оставить отзыв с оценкой 1–5."""
        response = self._client.post(
            f"{API_PREFIX}/reviews",
            json={"datasetId": dataset_id, "rating": rating, "text": text},
            headers=self._headers(),
        )
        self._raise(response)
        return dict(response.json())

    def rating(self, dataset_id: str) -> dict[str, Any]:
        """Рейтинг датасета по последнему отзыву каждого покупателя."""
        response = self._client.get(
            f"{API_PREFIX}/datasets/{dataset_id}/rating", headers=self._headers()
        )
        self._raise(response)
        return dict(response.json())


__all__ = ["API_PREFIX", "DEFAULT_GATEWAY_URL", "GatewayClient", "GatewayError"]
