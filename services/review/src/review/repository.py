"""Репозиторий отзывов (T081).

Правило рейтинга: учитывается только последний отзыв покупателя на датасет
(``DISTINCT ON (user_id) ... ORDER BY created_at DESC``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Numeric, SmallInteger, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from db.postgres import Base


class Review(Base):
    """Отзыв покупателя (``reviews.reviews``)."""

    __tablename__ = "reviews"
    __table_args__ = {"schema": "reviews"}

    review_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


async def add_review(session: AsyncSession, review: Review) -> Review:
    """Сохранить отзыв."""
    session.add(review)
    await session.flush()
    return review


async def list_reviews(
    session: AsyncSession, dataset_id: str, *, page: int, page_size: int
) -> tuple[list[Review], int]:
    """Постранично вернуть отзывы датасета (свежие первыми)."""
    conditions = [Review.dataset_id == dataset_id]
    total = int(
        (
            await session.execute(select(func.count()).select_from(Review).where(*conditions))
        ).scalar_one()
    )
    statement = (
        select(Review)
        .where(*conditions)
        .order_by(Review.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await session.execute(statement)).scalars().all()), total


async def latest_rating(session: AsyncSession, dataset_id: str) -> tuple[float, int]:
    """Средний рейтинг по последнему отзыву каждого покупателя и число отзывов."""
    statement = text("""
        SELECT AVG(rating)::float8 AS rating, COUNT(*)::int AS reviews_count
        FROM (
            SELECT DISTINCT ON (user_id) user_id, rating
            FROM reviews.reviews
            WHERE dataset_id = :dataset_id
            ORDER BY user_id, created_at DESC
        ) AS latest
        """)
    row = (await session.execute(statement, {"dataset_id": dataset_id})).mappings().one()
    rating = float(row["rating"]) if row["rating"] is not None else 0.0
    return rating, int(row["reviews_count"])


__all__ = ["Review", "add_review", "latest_rating", "list_reviews"]
