"""Сервис отзывов: оценка 1–5 и учёт только последнего отзыва (T082)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from contracts import ReviewEventPayload
from observability import ApiError
from observability.masking import mask_text

from . import repository as repo
from .events import ReviewPublisher, publish_review


def to_review_payload(review: repo.Review) -> ReviewEventPayload:
    """Представление отзыва для ответа API (текст замаскирован, m8)."""
    return ReviewEventPayload(
        eventId=review.review_id,
        userId=review.user_id,
        at=review.created_at,
        reviewId=review.review_id,
        datasetId=review.dataset_id,
        rating=review.rating,
        text=mask_text(review.text) if review.text else "",
    )


async def create_review(
    session: AsyncSession,
    publisher: ReviewPublisher,
    *,
    user_id: str,
    dataset_id: str,
    rating: int,
    text: str | None,
) -> repo.Review:
    """Сохранить отзыв (рейтинг 1–5; текст проходит PII-фильтр, m8)."""
    if not 1 <= rating <= 5:
        raise ApiError(400, "VALIDATION_ERROR", "Оценка должна быть от 1 до 5")
    review = repo.Review(
        review_id=f"rv_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        dataset_id=dataset_id,
        rating=rating,
        text=mask_text(text) if text else text,
    )
    await repo.add_review(session, review)
    await publish_review(publisher, review)
    return review


async def list_reviews(
    session: AsyncSession, dataset_id: str, *, page: int, page_size: int
) -> tuple[list[repo.Review], int]:
    """Список отзывов датасета."""
    return await repo.list_reviews(session, dataset_id, page=page, page_size=page_size)


async def dataset_rating(session: AsyncSession, dataset_id: str) -> tuple[float, int]:
    """Рейтинг датасета только по последнему отзыву каждого покупателя."""
    return await repo.latest_rating(session, dataset_id)


__all__ = ["create_review", "dataset_rating", "list_reviews", "to_review_payload"]
