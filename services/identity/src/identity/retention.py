"""Retention-job автоудаления PII по фиксированному сроку (T171, FR-037, SC-013).

PII покупателя хранится фиксированный срок (по умолчанию 12 месяцев) и
удаляется автоматически. Отдельный сценарий удаления по запросу не
реализуется: срока хранения достаточно.
"""

from __future__ import annotations

import asyncio
import calendar
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from observability import configure_logging, get_logger

DEFAULT_RETENTION_MONTHS: Final[int] = 12
_log = get_logger(__name__)

_DELETE_EXPIRED_PII = text("""
    DELETE FROM identity.pii_vault
    WHERE user_id IN (
        SELECT user_id FROM identity.users WHERE created_at < :cutoff
    )
    """)


def retention_cutoff(
    now: datetime | None = None, *, months: int = DEFAULT_RETENTION_MONTHS
) -> datetime:
    """Вернуть момент, раньше которого PII подлежит удалению."""
    if months < 1:
        raise ValueError(f"Срок хранения должен быть не меньше месяца, получено {months}")
    return _subtract_months(now or datetime.now(UTC), months)


def _subtract_months(moment: datetime, months: int) -> datetime:
    month_index = moment.month - 1 - months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    # День зажимается к последнему дню целевого месяца (например, 31 марта → 28 февраля).
    day = min(moment.day, _days_in_month(year, month))
    return moment.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


async def delete_expired_pii(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    months: int = DEFAULT_RETENTION_MONTHS,
) -> int:
    """Удалить PII покупателей старше срока хранения; вернуть число записей."""
    cutoff = retention_cutoff(now, months=months)
    result = await session.execute(_DELETE_EXPIRED_PII, {"cutoff": cutoff})
    deleted = int(getattr(result, "rowcount", 0) or 0)
    if deleted:
        _log.info("pii_retention_deleted", deleted=deleted, cutoff=cutoff.isoformat())
    return deleted


async def run_retention_job(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    months: int = DEFAULT_RETENTION_MONTHS,
) -> int:
    """Выполнить retention и зафиксировать результат."""
    return await delete_expired_pii(session, now=now, months=months)


async def run_with_session(session_factory: Callable[[], Any], *, months: int) -> int:
    """Открыть сессию, выполнить retention и закоммитить (scheduling-путь).

    Идемпотентность обеспечивает сам ``DELETE``: повторный запуск удаляет 0
    записей, если срок хранения ещё не наступил.
    """
    async with session_factory() as session:
        deleted = await run_retention_job(session, months=months)
        await session.commit()
    return deleted


async def run_retention_once(*, months: int | None = None) -> int:
    """Разовый запуск retention из окружения (compose-сервис/cron, FR-037)."""
    from config import get_settings
    from db.postgres import create_engine, create_session_factory

    settings = get_settings()
    resolved_months = months if months is not None else settings.app.pii_retention_months
    engine = create_engine(settings.postgres.async_dsn())
    factory = create_session_factory(engine)
    try:
        deleted = await run_with_session(factory, months=resolved_months)
    finally:
        await engine.dispose()
    _log.info("pii_retention_done", deleted=deleted, months=resolved_months)
    return deleted


def main() -> None:  # pragma: no cover - тонкая CLI-обёртка над run_retention_once
    """CLI-точка входа retention для compose-сервиса ``retention``."""
    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="identity-retention")
    asyncio.run(run_retention_once())


__all__ = [
    "DEFAULT_RETENTION_MONTHS",
    "delete_expired_pii",
    "main",
    "retention_cutoff",
    "run_retention_job",
    "run_retention_once",
    "run_with_session",
]
