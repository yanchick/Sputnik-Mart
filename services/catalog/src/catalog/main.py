"""FastAPI catalog: список, карточка, схема и образец датасета (T075)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from contracts import (
    ClickSource,
    Dataset,
    DatasetCategory,
    FileFormat,
    PagedResponse,
    QualityScoresUpdate,
    QualityScoresUpdated,
    SchemaField,
)
from db.postgres import create_engine, create_session_factory
from observability import (
    API_KEY_HEADER,
    ApiError,
    RequestIdMiddleware,
    bearer_user_id,
    configure_logging,
    get_logger,
    install_exception_handlers,
    paged_payload,
    user_id_from_headers,
)
from service_client import HttpServiceClient, ServiceClient, resolve_api_key

from . import service
from .clicks import ClickPublisher, NullClickPublisher, publish_click

_log = get_logger(__name__)

API_PREFIX = "/api/v1"


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    events: ClickPublisher | None = None,
    identity_client: ServiceClient | None = None,
) -> FastAPI:
    """Собрать приложение каталога."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Catalog Service", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    if session_factory is None:
        engine = create_engine(resolved.postgres.async_dsn())
        session_factory = create_session_factory(engine)
        app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = resolved
    app.state.events = events or NullClickPublisher()
    # Машинные ключи принадлежат identity; каталог проверяет их по HTTP (M6).
    app.state.identity_client = identity_client or HttpServiceClient("identity")

    async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
        factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
        session = factory()
        try:
            yield session
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

    async def require_operator(request: Request) -> str:
        """Операторский доступ к записи: Bearer или ``X-Api-Key`` (M6, как M4).

        Неподписанный токен и неизвестный/отозванный машинный ключ
        отклоняются единым конвертом 401.
        """
        settings: Settings = request.app.state.settings
        user_id = bearer_user_id(request.headers.get("Authorization"), settings.app.auth_secret)
        if user_id is not None:
            return user_id
        api_key = request.headers.get(API_KEY_HEADER)
        if api_key:
            key_user = await resolve_api_key(request.app.state.identity_client, api_key)
            if key_user is not None:
                return key_user
        raise ApiError(401, "UNAUTHORIZED", "Требуется аутентификация")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "catalog"}

    @app.get(
        f"{API_PREFIX}/datasets",
        response_model=PagedResponse[Dataset],
        tags=["datasets"],
    )
    async def list_datasets(
        _: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
        page: Annotated[int, Query(ge=1)] = 1,
        pageSize: Annotated[int, Query(ge=1, le=100)] = 20,
        category: DatasetCategory | None = None,
        minQuality: Annotated[float | None, Query(ge=0, le=1)] = None,
        sortBy: Annotated[
            str, Query(pattern="^(createdAt|lastUpdatedAt|pricePerUnit|qualityScore)$")
        ] = "createdAt",
    ) -> dict[str, object]:
        datasets, total = await service.list_datasets(
            session,
            page=page,
            page_size=pageSize,
            category=category.value if category else None,
            min_quality=minQuality,
            sort_by=sortBy,
        )
        return paged_payload(
            [dataset.model_dump(mode="json") for dataset in datasets], page, pageSize, total
        )

    @app.get(f"{API_PREFIX}/datasets/{{datasetId}}", response_model=Dataset, tags=["datasets"])
    async def get_dataset(
        datasetId: str,
        request: Request,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Dataset:
        dataset = await service.get_dataset(session, datasetId)
        await publish_click(request.app.state.events, datasetId, user_id, ClickSource.STORE)
        return dataset

    @app.get(
        f"{API_PREFIX}/datasets/{{datasetId}}/schema",
        response_model=list[SchemaField],
        tags=["datasets"],
    )
    async def get_schema(
        datasetId: str,
        _: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> list[SchemaField]:
        return await service.get_schema(session, datasetId)

    @app.get(f"{API_PREFIX}/datasets/{{datasetId}}/sample", tags=["datasets"])
    async def get_sample(
        datasetId: str,
        request: Request,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
        format: FileFormat = FileFormat.CSV,
    ) -> Response:
        content, media_type = await service.get_sample(session, datasetId, format)
        await publish_click(request.app.state.events, datasetId, user_id, ClickSource.SAMPLE)
        return Response(content=content, media_type=media_type)

    @app.post(
        f"{API_PREFIX}/datasets/quality-scores",
        response_model=QualityScoresUpdated,
        tags=["datasets"],
    )
    async def update_quality_scores(
        payload: QualityScoresUpdate,
        session: AsyncSession = Depends(get_session),
        _principal: str = Depends(require_operator),
    ) -> QualityScoresUpdated:
        """Внутренний операторский пересчёт ``qualityScore`` (M6).

        Единственная точка записи ``catalog.datasets.quality_score``: сюда
        обращается quality-service после пересчёта отчётов.
        """
        updated = await service.update_quality_scores(session, payload.scores)
        await session.commit()
        return QualityScoresUpdated(updated=updated, count=len(updated))

    return app


def main() -> None:
    """Запустить каталог под uvicorn."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="catalog")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "create_app", "main"]
