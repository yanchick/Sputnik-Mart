"""Unit-тесты DAG ``retention_pii``: артефакт и вызов job (M2, FR-037)."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

DAG_PATH = Path(__file__).resolve().parents[3] / "dags" / "retention_pii.py"


def _load_dag_module() -> ModuleType:
    sys.path.insert(0, str(DAG_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location("retention_pii", DAG_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(DAG_PATH.parent))


DAG_MODULE = _load_dag_module()


class _FakeResult:
    rowcount = 3


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.statements: list[Any] = []

    async def execute(self, statement: Any, _params: Any = None) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _FakeFactory:
    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> _FakeSession:
        return self.session


def test_dag_file_is_valid_python() -> None:
    ast.parse(DAG_PATH.read_text(encoding="utf-8"))


def test_retention_job_is_selectable() -> None:
    assert callable(DAG_MODULE.run_retention)
    assert callable(DAG_MODULE.execute_retention)


def test_execute_retention_invokes_job_and_commits() -> None:
    factory = _FakeFactory()

    deleted = asyncio.run(DAG_MODULE.execute_retention(factory, months=12))

    assert deleted == 3
    assert factory.session.committed is True
    assert len(factory.session.statements) == 1
