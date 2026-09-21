"""Silver/commerce → gold: витрина ``mart_sentiment_daily`` (T118).

Тональность отзывов считается детерминированным лексиконным анализатором
(без внешних ML-зависимостей), результат агрегируется по дню и датасету.
Загрузка идемпотентна по ключу ``(dt, dataset_id)``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

SENTIMENT_COLUMNS: tuple[str, ...] = (
    "dt",
    "dataset_id",
    "reviews",
    "avg_rating",
    "avg_sentiment",
    "positive",
    "negative",
)

POSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "хорош",
        "отличн",
        "супер",
        "нрав",
        "полезн",
        "удобн",
        "точно",
        "быстро",
        "качеств",
        "рекоменд",
        "good",
        "great",
        "excellent",
        "useful",
        "love",
        "nice",
    }
)
NEGATIVE_WORDS: frozenset[str] = frozenset(
    {
        "плох",
        "ужас",
        "ошибк",
        "неточн",
        "медлен",
        "дорог",
        "сложн",
        "разочаров",
        "bad",
        "awful",
        "error",
        "slow",
        "expensive",
        "hate",
        "poor",
    }
)


def score_text(text: str | None) -> float:
    """Оценить тональность текста в ``[-1, 1]`` по лексикону."""
    if not text:
        return 0.0
    normalized = text.lower()
    positive = sum(1 for word in POSITIVE_WORDS if word in normalized)
    negative = sum(1 for word in NEGATIVE_WORDS if word in normalized)
    total = positive + negative
    if total == 0:
        return 0.0
    return round((positive - negative) / total, 6)


def build_sentiment_rows(reviews: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """Агрегировать отзывы по дню и датасету в строки витрины."""
    grouped: dict[tuple[date, str], dict[str, float]] = {}
    for review in reviews:
        dataset_id = str(review.get("datasetId") or review.get("dataset_id") or "")
        if not dataset_id:
            continue
        created = _parse_datetime(
            review.get("at") or review.get("createdAt") or review.get("created_at")
        )
        day = created.date() if created else datetime.now(UTC).date()
        bucket = grouped.setdefault(
            (day, dataset_id), {"count": 0, "rating": 0.0, "sent": 0.0, "pos": 0, "neg": 0}
        )
        sentiment = score_text(review.get("text") if isinstance(review.get("text"), str) else None)
        rating = _to_float(review.get("rating"))
        bucket["count"] += 1
        bucket["rating"] += rating
        bucket["sent"] += sentiment
        if sentiment > 0.1:
            bucket["pos"] += 1
        elif sentiment < -0.1:
            bucket["neg"] += 1

    rows: list[list[Any]] = []
    for (day, dataset_id), bucket in sorted(grouped.items()):
        count = bucket["count"] or 1
        rows.append(
            [
                day,
                dataset_id,
                int(bucket["count"]),
                round(bucket["rating"] / count, 6),
                round(bucket["sent"] / count, 6),
                int(bucket["pos"]),
                int(bucket["neg"]),
            ]
        )
    return rows


async def load_sentiment_mart(client: Any, rows: Sequence[Sequence[Any]]) -> int:
    """Идемпотентно загрузить тональность; вернуть число строк."""
    if not rows:
        return 0
    keys = sorted({(row[0], row[1]) for row in rows})
    for dt, dataset_id in keys:
        await client.command(
            "ALTER TABLE mart_sentiment_daily DELETE WHERE "
            f"dt = toDate('{dt}') AND dataset_id = '{_escape(str(dataset_id))}' "
            "SETTINGS mutations_sync = 1"
        )
    await client.insert(
        "mart_sentiment_daily", [list(row) for row in rows], column_names=list(SENTIMENT_COLUMNS)
    )
    return len(rows)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _escape(value: str) -> str:
    return value.replace("'", "''")


__all__ = [
    "NEGATIVE_WORDS",
    "POSITIVE_WORDS",
    "SENTIMENT_COLUMNS",
    "build_sentiment_rows",
    "load_sentiment_mart",
    "score_text",
]
