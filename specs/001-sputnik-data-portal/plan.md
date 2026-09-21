# Implementation Plan: Демо-портал «Спутник Данные»

**Branch**: `001-sputnik-data-portal` | **Date**: 2026-09-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-sputnik-data-portal/spec.md`

## Summary

Требование — реализовать весь демонстрационный портал-маркетплейс данных «Спутник Данные» в объёме этапов M0–M4 и четырёх приоритезированных историй: витрина/покупка/кабинет (P1), путь данных датчиков от источника до витрины (P2), подписка и живой поток (P3), качество/наблюдаемость/безопасность/воспроизводимость (P4). Технический подход зафиксирован конституцией и ADR: единый Python-монорепозиторий (Python 3.12, `uv`, src-layout) с contract-first границами, асинхронный FastAPI-контур, событийная шина Redpanda (Kafka API) с моделью at-least-once и идемпотентными потребителями, медальон-озеро MinIO bronze → silver → ClickHouse gold, оркестрация Apache Airflow 2.9 и Python-фасад на Panel (HoloViz). Стенд поднимается одной командой в одном из трёх профилей `base`/`adv`/`demo`.

## Technical Context

**Language/Version**: Python 3.12, пакетный менеджер `uv`, src-layout-монорепозиторий.

**Primary Dependencies**: FastAPI + Starlette + Uvicorn/Gunicorn; Pydantic v2 + pydantic-settings; SQLAlchemy 2.0 async + Alembic + asyncpg; Redis 7 (redis-py); httpx (+ httpx-sse); aiokafka/confluent-kafka; boto3/aioboto3; Pandera + Great Expectations; pandas + Polars + PyArrow (Parquet); scikit-learn + statsmodels + Natasha/pymorphy; clickhouse-connect; Motor; Apache Airflow 2.9; structlog + OpenTelemetry + prometheus-client; фронтенд — Python + Panel (HoloViz)/Bokeh с `param`, `Tabulator`, `hvPlot`/`ECharts`.

**Storage**: PostgreSQL (операционные данные: identity/catalog/orders/reviews); ClickHouse (gold-витрины: `fact_readings` + Materialized Views и `mart_*`); MongoDB (гибкие метаданные провайдеров); MinIO (bronze/silver/отчёты/выгрузки); Redis (rate-limit/идемпотентность/сессии); Redpanda (Kafka API, события `sensors.readings*`, `commerce.*`, DLQ).

**Testing**: pytest + pytest-asyncio (unit); testcontainers (интеграционные с реальными Postgres/Redis/ClickHouse/Redpanda/MinIO); schemathesis (контрактные тесты против живых сервисов).

**Target Platform**: Linux + Docker Compose (профили `base`/`adv`/`demo`); работа в современных браузерах через Panel/Bokeh.

**Project Type**: мультисервисный web-монорепозиторий (backend-сервисы + Airflow DAGs + генераторы + Python-фронтенд на Panel).

**Performance Goals**: демонстрационный масштаб; свежее чтение видно в витрине/потоке не позднее двух интервалов генерации; профиль `base` готов к работе не более чем за 5 минут; запуск одной командой.

**Constraints**: без продакшн-нагрузки, реального железа и отказоустойчивости уровня enterprise; все данные синтетические и детерминированные; PII изолирован и маскируется в выгрузках; доставка at-least-once + идемпотентность; DLQ обязательна; единый язык стека.

**Scale/Scope**: 12 сервисов в `services/` + оркестрация (Airflow, `dags/`), всего 13 единиц; 6 инфраструктурных компонентов; этапы M0–M4; три профиля запуска.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Контракты прежде кода (NON-NEGOTIABLE)**: PASS — `specs/001-sputnik-data-portal/contracts/*.yaml` (OpenAPI/AsyncAPI) объявлены до реализации и служат источником истины; REST-модели — Pydantic v2, события — AsyncAPI с версией; контракты проверяются schemathesis и контрактными тестами.
- **Согласование контрактов**: рабочие копии контрактов в `specs/001-sputnik-data-portal/contracts/` авторитетны и расширены относительно оригиналов `Docs/specs/` — добавлены `X-Api-Key`, `429` + `Retry-After` и пагинация `{page, pageSize, total, totalPages, hasMore}`; перечисления в `data-model.md` приведены в соответствие с этими контрактами.
- **II. Асинхронность по умолчанию и единый рантайм**: PASS — все сервисы, DAGи и генераторы на Python 3.12/`uv`; I/O асинхронный (FastAPI/Starlette, SQLAlchemy 2.0 async + asyncpg, httpx, aiokafka); блокирующие вызовы выносятся в executor; конфиг только через pydantic-settings/переменные окружения. Единственная синхронная поверхность — процесс Python/Panel UI; он вынесен в отдельный процесс `web-vitrina` и не смешивается с async-контуром сервисов, поэтому нарушения нет.
- **III. Слоёные данные и контроль качества (NON-NEGOTIABLE)**: PASS — медальон bronze → silver → gold с обязательной валидацией на переходах; схемы слоёв на Pandera, аномалии и отчёты на Great Expectations; хранение в Parquet (PyArrow); идемпотентная запись по детерминированным ключам/партициям; неконформные записи уходят в карантин/DLQ; gold-витрины в ClickHouse, метаданные провайдеров в MongoDB.
- **IV. Событийная надёжность и идемпотентность**: PASS — обмен через Redpanda (Kafka API), топики `commerce.*`, `sensors.readings*`, DLQ; at-least-once с идемпотентными консьюмерами; ключи дедупликации в Redis; ретраи с backoff, «ядовитые» сообщения уходят в DLQ; эволюция схем только совместимая.
- **V. Наблюдаемость и тестируемость по умолчанию**: PASS — structlog с сквозным `requestId`, OpenTelemetry/prometheus-client, дашборды Grafana с метриками лага и свежести; pytest/pytest-asyncio, testcontainers, schemathesis; ruff/black/mypy — обязательные шлюзы.

## Project Structure

### Documentation (this feature)

```text
specs/001-sputnik-data-portal/
├── plan.md              # Этот файл (/speckit.plan)
├── research.md          # Phase 0 (/speckit.plan)
├── data-model.md        # Phase 1 (/speckit.plan)
├── quickstart.md        # Phase 1 (/speckit.plan)
├── contracts/           # Phase 1 (/speckit.plan) — OpenAPI/AsyncAPI
│   ├── README.md
│   ├── openapi-catalog.yaml
│   ├── openapi-order.yaml
│   ├── openapi-delivery.yaml
│   ├── asyncapi-commerce.yaml
│   └── asyncapi-content.yaml
└── tasks.md             # Phase 2 (/speckit.tasks — создаётся позже)
```

### Source Code (repository root)

```text
services/
├── web-vitrina/src/web_vitrina/       # Panel-фасад (витрина, кабинет, качество, SSE-график)
├── api-gateway/src/api_gateway/       # маршрутизация, auth, rate-limit, requestId, Swagger
├── identity/src/identity/             # покупатели, токены, API-ключи, PII/GDPR
├── catalog/src/catalog/               # каталог, провайдеры, цены, рейтинг качества
├── order/src/order/                   # заказы, подписки, скачивания
├── review/src/review/                 # отзывы (commerce + NLP-корпус)
├── delivery/src/delivery/             # выгрузка и SSE-потоки
├── sensor-gateway/src/sensor_gateway/ # приём чтений, receivedAt, публикация в Kafka
├── ingestion/src/ingestion/           # Kafka → MinIO bronze, DLQ
├── validation/src/validation/         # bronze → silver, аномалии, отчёт качества
├── transform/src/transform/           # silver → gold (фичи, временные ряды, сентимент)
└── quality/src/quality/               # Quality-page, SLA, алерты, qualityScore
libs/
├── contracts/                         # общие Pydantic/AsyncAPI-модели
├── db/                                # сессии/миграции Postgres, ClickHouse, Mongo
├── observability/                     # structlog, OpenTelemetry, прометей-метрики
└── config/                            # pydantic-settings, env-схемы
generators/
└── sim/src/sim/                       # sim-sensors/providers/buyers/dirty + CLI
dags/
├── ingest_readings.py
├── deliver_subscription.py
├── refresh_quality.py
└── sync_provider_exports.py
frontend/
└── panel/                             # переиспользуемые Panel-компоненты и тема
tests/
├── unit/
├── contract/
├── integration/
└── e2e/
infra/
├── docker/                            # Dockerfile-ы сервисов и инфраструктуры
├── clickhouse/                        # init SQL (fact_readings, MV, mart_*)
├── prometheus/                        # scrape-конфиг
└── grafana/                           # дашборды (лаг, свежесть)
docker-compose.yml                     # профили: docker compose --profile <base|adv|demo> up
Docs/
specs/
```

**Structure Decision**: Выбран единый contract-first монорепозиторий (ADR-0005): `specs/001-sputnik-data-portal/contracts/*.yaml` — источник истины, каждый сервис имеет пару «спека + папка `services/<name>/src/<pkg>/`», а общие модели/доступ к данным/наблюдаемость/config вынесены в `libs/`. Генераторы оформлены отдельным пакетом `sim` с CLI (ADR-0002), DAGи — в `dags/`, пользовательский фасад вынесен в отдельный процесс Python/Panel (ADR-0006), а профили запуска управляются одной командой `docker compose --profile <base|adv|demo> up`, а не кодом. Это даёт один язык на всём стеке, отсутствие второй JS-сборки и воспроизводимый запуск одной командой.

## Complexity Tracking

Нарушений конституции нет.
