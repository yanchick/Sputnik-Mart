"""Тест hard gates контракт-линта и CI (T161, FR-031, SC-010)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CONTRACT_LINT = REPO_ROOT / "scripts" / "contract_lint.py"
GITIGNORE = REPO_ROOT / ".gitignore"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _load_contract_lint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("contract_lint", CONTRACT_LINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_workflow_declares_all_hard_gates() -> None:
    raw = CI_WORKFLOW.read_text(encoding="utf-8")
    yaml.safe_load(raw)  # workflow обязан оставаться валидным YAML

    for required in (
        "ruff check",
        "black --check",
        "mypy",
        "pytest tests/unit",
        "pytest tests/contract",
        "contract_lint.py",
        "docker/build-push-action",
        "release-gate",
    ):
        assert required in raw, f"CI-шлюз не содержит обязательный шаг: {required}"


def test_contract_lint_passes_on_repository_contracts() -> None:
    module = _load_contract_lint()
    assert module.main() == 0


def test_contract_lint_blocks_on_broken_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_contract_lint()
    (tmp_path / "openapi-catalog.yaml").write_text("openapi: [broken\n", encoding="utf-8")
    monkeypatch.setattr(module, "CONTRACT_DIR", tmp_path)

    exit_code = module.main()

    assert exit_code == 1
    assert "FAIL" in capsys.readouterr().err


def test_env_secret_hygiene() -> None:
    """QR-10: ``.env`` исключён из образов/гита, а пример содержит предупреждение."""
    gitignore = GITIGNORE.read_text(encoding="utf-8")
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    example = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert ".env" in gitignore
    assert "!.env.example" in gitignore
    assert ".env" in dockerignore
    assert "!.env.example" in dockerignore

    assert "ДЕМО" in example.upper()
    assert "PII_ENCRYPTION_KEY" in example
    assert "DEFAULT_PII_KEY" in example
