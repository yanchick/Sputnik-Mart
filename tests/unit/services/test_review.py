"""Unit-тесты review: оценка 1–5 и payload события (T065)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from review.events import NullReviewPublisher, build_review_event
from review.repository import Review
from review.service import create_review, to_review_payload

from observability import ApiError
from support import FakeAddSession

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _review(rating: int, text: str = "ok") -> Review:
    return Review(
        review_id="rv_1",
        user_id="us_1",
        dataset_id="ds_weather-stations",
        rating=rating,
        text=text,
        created_at=NOW,
    )


def test_to_review_payload() -> None:
    payload = to_review_payload(_review(5, "Отлично"))

    assert payload.reviewId == "rv_1"
    assert payload.rating == 5
    assert payload.text == "Отлично"


@pytest.mark.parametrize("rating", [1, 3, 5])
async def test_create_review_accepts_valid_rating(rating: int) -> None:
    session = FakeAddSession()
    publisher = NullReviewPublisher()

    review = await create_review(
        session,  # type: ignore[arg-type]
        publisher,
        user_id="us_1",
        dataset_id="ds_weather-stations",
        rating=rating,
        text="ok",
    )

    assert review.review_id.startswith("rv_")
    assert review.rating == rating
    assert len(publisher.published) == 1


@pytest.mark.parametrize("rating", [0, 6, -1])
async def test_create_review_rejects_out_of_range(rating: int) -> None:
    session = FakeAddSession()
    publisher = NullReviewPublisher()

    with pytest.raises(ApiError) as error:
        await create_review(
            session,  # type: ignore[arg-type]
            publisher,
            user_id="us_1",
            dataset_id="ds_weather-stations",
            rating=rating,
            text=None,
        )

    assert error.value.status_code == 400
    assert error.value.code == "VALIDATION_ERROR"
    assert session.added == []


async def test_create_review_scrubs_pii_before_persistence() -> None:
    """m8: email/телефон в тексте маскируются до записи в БД."""
    session = FakeAddSession()
    publisher = NullReviewPublisher()

    review = await create_review(
        session,  # type: ignore[arg-type]
        publisher,
        user_id="us_1",
        dataset_id="ds_weather-stations",
        rating=5,
        text="Пишите buyer@sputnik.demo или +79261234567",
    )

    assert "buyer@sputnik.demo" not in (review.text or "")
    assert "+79261234567" not in (review.text or "")
    assert "***@sputnik.demo" in (review.text or "")
    assert len(publisher.published) == 1


def test_review_payload_and_event_are_scrubbed() -> None:
    """m8: commerce.reviews и ответ API не содержат PII."""
    review = _review(5, "контакт test@sputnik.demo, тел +79261234567")

    payload = to_review_payload(review)
    event = build_review_event(review)

    assert payload.text == event["text"]
    assert "test@sputnik.demo" not in event["text"]
    assert "+79261234567" not in event["text"]
