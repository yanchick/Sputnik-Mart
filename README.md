# Спутник Данные

Монорепозиторий демо-портала маркетплейса данных «Спутник Данные» (проект ДДЕ).
Стек: Python 3.12 + `uv`, FastAPI, Redpanda (Kafka API),
Silo (MinIO-совместимый, Docker Hub), ClickHouse, MongoDB, PostgreSQL, Redis,
Apache Airflow и фасад на Panel (HoloViz).

Контракты — источник истины: `specs/001-sputnik-data-portal/contracts/*.yaml`.
План и задачи: `specs/001-sputnik-data-portal/plan.md`, `tasks.md`.

## Быстрый старт

```bash
cp .env.example .env
uv sync --all-packages --dev
docker compose --profile base up -d
```

После старта фасад — http://localhost:8050, Swagger/OpenAPI gateway —
http://localhost:8000/docs. Остановить: `docker compose --profile base down`.

## Профили запуска

| Профиль | Команда | Состав | Назначение |
| --- | --- | --- | --- |
| `base` | `docker compose --profile base up` | PostgreSQL, Redis, `identity`, `catalog`, `order`, `review`, `delivery`, `api-gateway`, `web-vitrina`, seed | MVP US1: витрина, покупка, кабинет |
| `adv` | `docker compose --profile adv up` | base + Redpanda, MinIO, ClickHouse, MongoDB, Airflow, Prometheus, Grafana, `sensor-gateway`, `ingestion`, `validation`, `transform`, `quality` | US2/US3: конвейер данных и живой поток |
| `demo` | `docker compose --profile demo up` | как `adv` + предзаготовленные данные (`prepare_demo_data.py`, seed 42) | сквозная приёмка M0–M4 |

Особенности:

- `base` готов к работе не более чем за 5 минут (SC-001).
- `demo` поднимает `demo-data` — одноразовый сервис подготовки репозитория
  данных для быстрого показа.
- Профили управляются переменной `PROFILE` и флагами compose; отдельного кода
  для переключения нет.

## Порты

| Компонент | Порт | Компонент | Порт |
| --- | --- | --- | --- |
| api-gateway | 8000 | catalog | 8001 |
| identity | 8002 | order | 8003 |
| review | 8004 | delivery | 8005 |
| sensor-gateway | 8006 | quality | 8007 |
| web-vitrina | 8050 | Airflow | 8081 |
| Redpanda Console | 8080 | Prometheus | 9090 |
| Grafana | 3000 | MinIO Console | 9001 |
| ClickHouse | 8123 | PostgreSQL | 5432 |

> Хранилище озера — Silo (`pgsty/silo`) с Docker Hub: официальные образы MinIO
> удалены из Docker Hub, а Quay закрыл анонимный доступ в 2026. S3 API,
> переменные `MINIO_*` и консоль на `9001` сохранены.

Порт Grafana можно переопределить: `GRAFANA_PORT=3300 docker compose --profile adv up -d`.

## Разработка

```bash
uv sync --all-packages --dev   # создать окружение
make lint                      # ruff + black --check + mypy
make test                      # unit-тесты
make contract                  # контрактные тесты
make contract-lint             # линт OpenAPI/AsyncAPI
```

Полный шлюз качества (как в CI):

```bash
uv run ruff check .
uv run ruff format --check .
uv run black --check .
uv run mypy .
uv run python scripts/contract_lint.py
uv run pytest -q
```

Порог покрытия — 80% (`[tool.coverage.report] fail_under` в `pyproject.toml`).
Изменения схемы БД выполняются только через Alembic в `libs/db/migrations/`.

## Генераторы

```bash
uv run sim sensors --seed 42 --periods 24 --out /tmp/readings.ndjson
uv run sim dirty --input /tmp/readings.ndjson --seed 42 --missing 0.1 --out /tmp/dirty.ndjson
```

Одинаковый `seed` даёт идентичный результат (SC-003).

## Диагностика

- **Порт занят.** Освободить порт из таблицы выше или остановить старый профиль:
  `docker compose --profile <base|adv|demo> down`.
- **Сервис не поднимается.** `docker compose --profile <profile> logs <service>`;
  проверить `.env` и healthcheck зависимостей.
- **Пустой каталог / нет демо-аккаунтов.** Убедиться, что выполнен seed
  (compose-сервис `seed` / генератор `generators/sim`, `SIM_SEED=42`).
- **Нет свежих данных в `adv`/`demo`.** Проверить Redpanda, MinIO, ClickHouse и
  прогон DAGов Airflow (см. `docs/runbooks/pipeline.md`).
- **429 при выгрузке/потоке.** Ориентироваться на `Retry-After`; лимиты
  настраиваются демонстрационными значениями по умолчанию (SC-014).
- **PII в выгрузке.** PII маскируется (`***@domain`) и хранится изолированно;
  см. `docs/architecture/overview.md`.
- **Битые записи.** Смотреть `docs/runbooks/dlq.md`.

## Документация

- Архитектура: `docs/architecture/overview.md`.
- Runbooks: `docs/runbooks/pipeline.md`, `docs/runbooks/dlq.md`,
  `docs/runbooks/streams.md`.
- Quickstart и приёмка: `specs/001-sputnik-data-portal/quickstart.md`,
  `Docs/spec-kit/acceptance.md`.
- Конституция проекта: `.specify/memory/constitution.md`.
