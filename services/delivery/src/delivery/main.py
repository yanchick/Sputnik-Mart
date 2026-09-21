"""FastAPI delivery: выгрузка датасета и живой SSE-поток (T086)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from contracts import FileFormat, SubscriptionStatus
from db.postgres import create_engine, create_session_factory
from observability import (
    USER_ID_HEADER,
    ApiError,
    RequestIdMiddleware,
    configure_logging,
    get_logger,
    install_exception_handlers,
    user_id_from_headers,
)
from service_client import HttpServiceClient, ServiceClient

from . import access, downloads, service
from .idempotency import ReadingDeduplicator, create_reading_deduplicator
from .sse import SSE_MEDIA_TYPE, stream_frames
from .streams import ReadingSource, create_reading_source

_log = get_logger(__name__)

API_PREFIX = "/api/v1"
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    events: downloads.DownloadPublisher | None = None,
    reading_source: ReadingSource | None = None,
    deduplicator: ReadingDeduplicator | None = None,
    order_client: ServiceClient | None = None,
    identity_client: ServiceClient | None = None,
    catalog_client: ServiceClient | None = None,
    ping_interval: float = 15.0,
) -> FastAPI:
    """Собрать приложение доставки."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Delivery Service", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    if session_factory is None:
        engine = create_engine(resolved.postgres.async_dsn())
        session_factory = create_session_factory(engine)
        app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = resolved
    app.state.events = events or downloads.NullDownloadPublisher()
    app.state.reading_source = reading_source or create_reading_source(resolved)
    app.state.deduplicator = deduplicator or create_reading_deduplicator(
        os.environ.get("REDIS_URL")
    )
    app.state.ping_interval = ping_interval
    # Права/ключи/схема принадлежат order/identity/catalog (M6).
    app.state.order_client = order_client or HttpServiceClient("order")
    app.state.identity_client = identity_client or HttpServiceClient("identity")
    app.state.catalog_client = catalog_client or HttpServiceClient("catalog")

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

    async def resolve_user(request: Request) -> str:
        user_id = user_id_from_headers(
            request.headers.get("Authorization"),
            None,
            request.app.state.settings.app.auth_secret,
        )
        if user_id is not None:
            return user_id
        api_key = request.headers.get("X-Api-Key")
        if api_key:
            resolved_user = await access.user_id_for_api_key(
                request.app.state.identity_client, api_key
            )
            if resolved_user is not None:
                return resolved_user
        raise ApiError(401, "UNAUTHORIZED", "Требуется аутентификация")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "delivery"}

    @app.get(f"{API_PREFIX}/datasets/{{datasetId}}/download", tags=["downloads"])
    async def download_dataset(
        datasetId: str,
        request: Request,
        session: AsyncSession = Depends(get_session),
        format: FileFormat = FileFormat.CSV,
    ) -> Response:
        user_id = await resolve_user(request)
        if not await access.has_download_access(request.app.state.order_client, user_id, datasetId):
            raise ApiError(403, "FORBIDDEN", "Датасет не оплачен")
        fields = await service.load_fields(request.app.state.catalog_client, datasetId, user_id)
        if not fields:
            raise ApiError(404, "NOT_FOUND", "Схема датасета не найдена")
        content, media_type, extension = service.render_content(datasetId, fields, format)
        record = await downloads.record_download(
            session, user_id=user_id, dataset_id=datasetId, fmt=format, size=len(content)
        )
        await downloads.publish_download(request.app.state.events, record)
        await _fulfill_order(request.app.state.order_client, user_id, datasetId)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{datasetId}.{extension}"'},
        )

    @app.get(f"{API_PREFIX}/streams/{{subscriptionId}}", tags=["streams"])
    async def open_stream(
        subscriptionId: str,
        request: Request,
    ) -> StreamingResponse:
        user_id = await resolve_user(request)
        subscription = await access.get_subscription(
            request.app.state.order_client, subscriptionId, user_id
        )
        if subscription is None:
            raise ApiError(404, "NOT_FOUND", "Подписка не найдена")
        if str(subscription["user_id"]) != user_id:
            raise ApiError(403, "FORBIDDEN", "Подписка принадлежит другому покупателю")
        if str(subscription["status"]) != SubscriptionStatus.SUB_ACTIVE.value:
            raise ApiError(403, "FORBIDDEN", "Подписка не активна: поток недоступен")

        readings = request.app.state.reading_source.stream(subscription)
        frames = stream_frames(
            readings,
            request.app.state.deduplicator,
            ping_interval=request.app.state.ping_interval,
        )
        return StreamingResponse(frames, media_type=SSE_MEDIA_TYPE, headers=STREAM_HEADERS)

    return app


async def _fulfill_order(order: ServiceClient, user_id: str, dataset_id: str) -> None:
    """Перевести оплаченный заказ в ``ORDER_FULFILLED`` после выдачи (m12)."""
    await order.post_json(
        "/api/v1/orders/fulfill",
        json={"datasetId": dataset_id},
        headers={USER_ID_HEADER: user_id},
    )


def main() -> None:
    """Запустить сервис доставки под uvicorn."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="delivery")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "create_app", "main"]
