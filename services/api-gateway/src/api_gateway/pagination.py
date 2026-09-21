"""Единая пагинация ``{page,pageSize,total,totalPages,hasMore}`` (T092, FR-034).

Каноническая реализация живёт в :mod:`observability.pagination`; этот модуль
переиспользует её и добавляет gateway-специфичную нормализацию проксируемых
JSON-ответов, поэтому формула пагинации не дублируется.
"""

from __future__ import annotations

import json
from typing import Any

from observability.pagination import build_pagination


def normalize_paged_body(body: Any) -> Any:
    """Гарантировать наличие полного набора полей пагинации в ответе."""
    if not isinstance(body, dict):
        return body
    pagination = body.get("pagination")
    if not isinstance(pagination, dict):
        return body
    page = int(pagination.get("page", 1) or 1)
    page_size = int(pagination.get("pageSize", 20) or 20)
    total = int(pagination.get("total", 0) or 0)
    body["pagination"] = build_pagination(page, page_size, total)
    return body


def normalize_json_content(content: bytes, content_type: str | None) -> bytes:
    """Привести конверт пагинации в JSON-ответе к контрактному виду (FR-034).

    Нетронутыми проходят не-JSON тела, битый JSON и объекты без ``pagination``.
    """
    if not content or content_type is None or "application/json" not in content_type:
        return content
    try:
        body = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return content
    if not isinstance(body, dict) or not isinstance(body.get("pagination"), dict):
        return content
    return json.dumps(normalize_paged_body(body), ensure_ascii=False).encode("utf-8")


__all__ = ["build_pagination", "normalize_json_content", "normalize_paged_body"]
