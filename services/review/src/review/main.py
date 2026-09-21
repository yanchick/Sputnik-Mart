"""FastAPI review: список/создание отзывов и рейтинг датасета (T083)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from contracts import ReviewEventPayload
from db.postgres import create_engine, create_session_factory
from observability import (
    ApiError,
    RequestIdMiddleware,
    configure_logging,
    get_logger,
    install_exception_handlers,
    paged_payload,
    user_id_from_headers,
)

from . import service
from .events import NullReviewPublisher, ReviewPublisher

_log = get_logger(__name__)

API_PREFIX = "/api/v1"


class CreateReviewRequest(BaseModel):
    """Тело запроса на создание отзыва."""

    model_config = ConfigDict(extra="forbid")

    datasetId: str = Field(pattern=r"^ds_[a-z0-9_-]+$")
    rating: int = Field(ge=1, le=5)
    text: str | None = None


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    events: ReviewPublisher | None = None,
) -> FastAPI:
    """Собрать приложение отзывов."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Review Service", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    if session_factory is None:
        engine = create_engine(resolved.postgres.async_dsn())
        session_factory = create_session_factory(engine)
        app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = resolved
    publisher: ReviewPublisher = events or NullReviewPublisher()
    app.state.events = publisher

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
        return {"status": "ok", "service": "review"}

    @app.get(f"{API_PREFIX}/reviews", tags=["reviews"])
    async def list_reviews(
        datasetId: str = Query(min_length=1),
        _: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
        page: int = Query(default=1, ge=1),
        pageSize: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, object]:
        reviews, total = await service.list_reviews(
            session, datasetId, page=page, page_size=pageSize
        )
        return paged_payload(
            [service.to_review_payload(review).model_dump(mode="json") for review in reviews],
            page,
            pageSize,
            total,
        )

    @app.post(
        f"{API_PREFIX}/reviews",
        response_model=ReviewEventPayload,
        status_code=201,
        tags=["reviews"],
    )
    async def create_review(
        payload: CreateReviewRequest,
        request: Request,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> ReviewEventPayload:
        review = await service.create_review(
            session,
            request.app.state.events,
            user_id=user_id,
            dataset_id=payload.datasetId,
            rating=payload.rating,
            text=payload.text,
        )
        return service.to_review_payload(review)

    @app.get(f"{API_PREFIX}/datasets/{{datasetId}}/rating", tags=["reviews"])
    async def get_rating(
        datasetId: str,
        _: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, object]:
        rating, reviews_count = await service.dataset_rating(session, datasetId)
        return {"datasetId": datasetId, "rating": round(rating, 3), "reviewsCount": reviews_count}

    return app


def main() -> None:
    """Запустить сервис отзывов под uvicorn."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="review")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "CreateReviewRequest", "create_app", "main"]
