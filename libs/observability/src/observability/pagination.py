"""Единая пагинация ``{page,pageSize,total,totalPages,hasMore}`` (FR-034)."""

from __future__ import annotations

from typing import Any


def build_pagination(page: int, page_size: int, total: int) -> dict[str, Any]:
    """Построить метаданные пагинации из номера страницы и общего числа."""
    safe_size = max(page_size, 1)
    total_pages = (total + safe_size - 1) // safe_size
    has_more = page * safe_size < total
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "hasMore": has_more,
    }


def paged_payload(data: list[Any], page: int, page_size: int, total: int) -> dict[str, Any]:
    """Собрать ``{data,pagination}`` в camelCase для JSON-ответа."""
    return {"data": data, "pagination": build_pagination(page, page_size, total)}


__all__ = ["build_pagination", "paged_payload"]
