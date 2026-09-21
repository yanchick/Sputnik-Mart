# Спутник Данные — служебные цели (Phase 1, T015).
# Профиль по умолчанию: base. Пример: make up PROFILE=adv

PROFILE ?= base
COMPOSE ?= docker compose
UV ?= uv

.PHONY: help up up-base up-adv up-demo down down-base down-adv down-demo \
        logs lock lint format test contract contract-lint

help:
	@echo "Профили: base | adv | demo"
	@echo "make up PROFILE=base   — поднять стек в профиле"
	@echo "make down PROFILE=base — остановить стек"
	@echo "make lint              — ruff + black --check + mypy"
	@echo "make test              — unit-тесты"
	@echo "make contract          — контрактные тесты"
	@echo "make contract-lint     — линт OpenAPI/AsyncAPI"

up:
	$(COMPOSE) --profile $(PROFILE) up -d

up-base:
	$(COMPOSE) --profile base up -d

up-adv:
	$(COMPOSE) --profile adv up -d

up-demo:
	$(COMPOSE) --profile demo up -d

down:
	$(COMPOSE) --profile $(PROFILE) down

down-base:
	$(COMPOSE) --profile base down

down-adv:
	$(COMPOSE) --profile adv down

down-demo:
	$(COMPOSE) --profile demo down

logs:
	$(COMPOSE) --profile $(PROFILE) logs -f

lock:
	$(UV) lock

lint:
	$(UV) run ruff check .
	$(UV) run black --check .
	$(UV) run mypy .

format:
	$(UV) run ruff check --fix .
	$(UV) run black .

test:
	$(UV) run pytest tests/unit

contract:
	$(UV) run pytest tests/contract

contract-lint:
	$(UV) run python scripts/contract_lint.py
