"""Unit-тесты рантайм-путей retention: scheduling-обёртки (M2, FR-037)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from identity.retention import run_retention_once, run_with_session

import config
import db.postgres
from config import Settings

pytestmark = pytest.mark.unit


class _FakeResult:
    rowcount = 4


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def execute(self, _statement: Any, _params: Any = None) -> _FakeResult:
        return _FakeResult()

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_run_with_session_commits_and_returns_deleted() -> None:
    session = _FakeSession()

    deleted = asyncio.run(run_with_session(lambda: session, months=12))

    assert deleted == 4
    assert session.committed is True


def test_run_retention_once_builds_engine_and_uses_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    engine = _FakeEngine()
    monkeypatch.setattr(config, "get_settings", lambda: Settings())
    monkeypatch.setattr(db.postgres, "create_engine", lambda _dsn: engine)
    monkeypatch.setattr(db.postgres, "create_session_factory", lambda _engine: lambda: session)

    deleted = asyncio.run(run_retention_once())

    assert deleted == 4
    assert session.committed is True
    assert engine.disposed is True
