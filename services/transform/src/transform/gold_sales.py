"""Commerce → gold: витрина ``mart_sales_daily`` (T147, FR-025).

Бизнес-события агрегируются по дню и датасету: заказы и подписки дают число
покупок (``orders``), скачивания — ``downloads``, просмотры — ``clicks``,
а сумма заказов — ``gross_amount``. Загрузка идемпотентна по ключу
``(dt, dataset_id)`` — перед вставкой прежние строки за день удаляются (upsert).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

SALES_COLUMNS: tuple[str, ...] = (
    "dt",
    "dataset_id",
    "orders",
    "downloads",
    "clicks",
    "gross_amount",
)


def build_sales_rows(
    orders: Sequence[Mapping[str, Any]],
    downloads: Sequence[Mapping[str, Any]],
    *,
    subscriptions: Sequence[Mapping[str, Any]] = (),
    clicks: Sequence[Mapping[str, Any]] = (),
) -> list[list[Any]]:
    """Агрегировать commerce-события по дню и датасету.

    Заказы и подписки увеличивают ``orders`` (подписка — тоже покупка),
    скачивания — ``downloads``, просмотры — ``clicks``; ``gross_amount``
    набирается только из суммы заказов.
    """
    buckets: dict[tuple[date, str], dict[str, float]] = {}
    for order in orders:
        bucket = _bucket_for(buckets, order, ("at", "createdAt", "created_at"))
        if bucket is None:
            continue
        bucket["orders"] += 1
        bucket["amount"] += _to_float(order.get("amount"))
    for subscription in subscriptions:
        bucket = _bucket_for(
            buckets, subscription, ("at", "startedAt", "started_at", "createdAt", "created_at")
        )
        if bucket is not None:
            bucket["orders"] += 1
    for download in downloads:
        bucket = _bucket_for(buckets, download, ("at", "requestedAt", "requested_at"))
        if bucket is not None:
            bucket["downloads"] += 1
    for click in clicks:
        bucket = _bucket_for(buckets, click, ("at",))
        if bucket is not None:
            bucket["clicks"] += 1

    rows: list[list[Any]] = []
    for (day, dataset_id), bucket in sorted(buckets.items()):
        rows.append(
            [
                day,
                dataset_id,
                int(bucket["orders"]),
                int(bucket["downloads"]),
                int(bucket["clicks"]),
                round(bucket["amount"], 2),
            ]
        )
    return rows


def _bucket_for(
    buckets: dict[tuple[date, str], dict[str, float]],
    event: Mapping[str, Any],
    timestamp_keys: tuple[str, ...],
) -> dict[str, float] | None:
    """Найти/создать накопитель дня и датасета; ``None`` — событие без датасета."""
    dataset_id = str(event.get("datasetId") or event.get("dataset_id") or "")
    if not dataset_id:
        return None
    day = _event_day(_first(event, timestamp_keys))
    return buckets.setdefault(
        (day, dataset_id), {"orders": 0, "downloads": 0, "clicks": 0, "amount": 0.0}
    )


def _first(event: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if event.get(key) is not None:
            return event[key]
    return None


async def load_sales_mart(client: Any, rows: Sequence[Sequence[Any]]) -> int:
    """Идемпотентно загрузить продажи за дни/датасеты; вернуть число строк."""
    if not rows:
        return 0
    keys = sorted({(row[0], row[1]) for row in rows})
    for dt, dataset_id in keys:
        await client.command(
            "ALTER TABLE mart_sales_daily DELETE WHERE "
            f"dt = toDate('{dt}') AND dataset_id = '{_escape(str(dataset_id))}' "
            "SETTINGS mutations_sync = 1"
        )
    await client.insert(
        "mart_sales_daily", [list(row) for row in rows], column_names=list(SALES_COLUMNS)
    )
    return len(rows)


def _event_day(value: Any) -> date:
    parsed = _parse_datetime(value)
    return parsed.date() if parsed else datetime.now(UTC).date()


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


__all__ = ["SALES_COLUMNS", "build_sales_rows", "load_sales_mart"]
