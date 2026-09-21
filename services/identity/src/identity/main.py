"""FastAPI identity: вход по демо-аккаунту, профиль и машинные ключи (T071)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from db.postgres import create_engine, create_session_factory
from observability import (
    ApiError,
    RequestIdMiddleware,
    configure_logging,
    get_logger,
    hash_api_key,
    install_exception_handlers,
    paged_payload,
    user_id_from_headers,
)
from service_client import HttpServiceClient, ServiceClient

from . import api_keys as api_key_module
from . import repository as repo
from . import service
from .schemas import (
    ApiKeyCreated,
    ApiKeyResolution,
    ApiKeyResolveRequest,
    LoginRequest,
    LoginResponse,
    UserProfile,
)

_log = get_logger(__name__)

API_PREFIX = "/api/v1"


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    order_client: ServiceClient | None = None,
) -> FastAPI:
    """Собрать приложение identity с внедряемой фабрикой сессий."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Identity Service", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    if session_factory is None:
        engine = create_engine(resolved.postgres.async_dsn())
        session_factory = create_session_factory(engine)
        app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = resolved
    # Подписки — данные order-сервиса; identity читает их только по HTTP (M6).
    app.state.order_client = order_client or HttpServiceClient("order")

    async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
        factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
        session = factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def require_user(request: Request) -> str:
        user_id = user_id_from_headers(
            request.headers.get("Authorization"),
            request.headers.get("X-User-Id"),
            request.app.state.settings.app.auth_secret,
        )
        if user_id is None:
            raise ApiError(401, "UNAUTHORIZED", "Требуется аутентификация")
        return user_id

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "identity"}

    @app.post(f"{API_PREFIX}/auth/login", response_model=LoginResponse, tags=["auth"])
    async def login(
        payload: LoginRequest,
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> LoginResponse:
        return await service.login(
            session, payload.email, payload.password, request.app.state.settings
        )

    @app.get(f"{API_PREFIX}/users/me", response_model=UserProfile, tags=["users"])
    async def me(
        request: Request,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> UserProfile:
        return await service.get_profile(
            session, user_id, request.app.state.settings.app.pii_encryption_key
        )

    @app.get(f"{API_PREFIX}/users/{{userId}}/subscriptions", tags=["users"])
    async def subscriptions(
        userId: str,
        request: Request,
        user_id: str = Depends(require_user),
    ) -> dict[str, object]:
        _ensure_self(userId, user_id)
        views = await service.list_subscriptions(request.app.state.order_client, userId)
        return paged_payload(
            [view.model_dump(mode="json") for view in views], 1, max(len(views), 1), len(views)
        )

    @app.get(f"{API_PREFIX}/users/{{userId}}/api-keys", tags=["users"])
    async def list_keys(
        userId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> list[dict[str, object]]:
        _ensure_self(userId, user_id)
        keys = await repo.list_api_keys(session, userId)
        return [service.to_api_key_view(key).model_dump(mode="json") for key in keys]

    @app.post(
        f"{API_PREFIX}/users/{{userId}}/api-keys",
        response_model=ApiKeyCreated,
        status_code=201,
        tags=["users"],
    )
    async def create_key(
        userId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> ApiKeyCreated:
        _ensure_self(userId, user_id)
        api_key, plaintext = await api_key_module.issue_api_key(session, userId)
        return service.to_api_key_created(api_key, plaintext)

    @app.delete(
        f"{API_PREFIX}/users/{{userId}}/api-keys/{{keyId}}", status_code=204, tags=["users"]
    )
    async def revoke_key(
        userId: str,
        keyId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Response:
        _ensure_self(userId, user_id)
        revoked = await api_key_module.revoke_key(session, userId, keyId)
        if not revoked:
            raise ApiError(404, "NOT_FOUND", "Ключ не найден")
        return Response(status_code=204)

    @app.post(
        f"{API_PREFIX}/api-keys/resolve",
        response_model=ApiKeyResolution,
        tags=["users"],
    )
    async def resolve_api_key(
        payload: ApiKeyResolveRequest,
        session: AsyncSession = Depends(get_session),
    ) -> ApiKeyResolution:
        """Проверить машинный ключ для других сервисов (M6).

        Возвращает владельца активного ключа или ``None``: отозванный и
        неизвестный ключ одинаково недействительны. Публично через gateway
        маршрут недоступен — вызывается только service-to-service.
        """
        api_key = await repo.get_api_key_by_hash(session, hash_api_key(payload.apiKey))
        if api_key is None or api_key.revoked_at is not None:
            return ApiKeyResolution(userId=None)
        return ApiKeyResolution(userId=api_key.user_id)

    return app


def _ensure_self(path_user_id: str, principal_user_id: str) -> None:
    if path_user_id != principal_user_id:
        raise ApiError(403, "FORBIDDEN", "Доступ только к своим данным")


def main() -> None:
    """Запустить identity под uvicorn."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="identity")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "create_app", "main"]
