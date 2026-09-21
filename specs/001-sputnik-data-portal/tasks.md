# Tasks: Демо-портал «Спутник Данные»

**Input**: Design documents from `/specs/001-sputnik-data-portal/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Тесты ОБЯЗАТЕЛЬНЫ (Конституция, Принцип V «Наблюдаемость и тестируемость по умолчанию»). Контрактные, unit- и интеграционные тесты включены отдельными задачами и пишутся ДО реализации; schemathesis, testcontainers, pytest/pytest-asyncio — обязательные шлюзы выпуска.

**Organization**: Задачи сгруппированы по пользовательским историям, чтобы каждую можно было реализовать и протестировать независимо. Приоритеты соответствуют spec.md: US1 (P1, MVP, профиль `base`), US2 (P2, профиль `adv`), US3 (P3), US4 (P4, сквозная приёмка M0–M4, профиль `demo`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Можно выполнять параллельно (разные файлы, нет взаимных зависимостей)
- **Метка истории**: К какой пользовательской истории относится задача (например, US1, US2, US3, US4)
- В описании каждой задачи указан точный путь к файлу

## Path Conventions

- Монорепозиторий contract-first: `services/<name>/src/<pkg>/` — реализация сервисов; `libs/<name>/src/<pkg>/` — общие библиотеки (`contracts`, `db`, `observability`, `config`)
- `generators/sim/src/sim/` — генераторы; `dags/` — Airflow DAGs; `services/web-vitrina/src/web_vitrina/` — фасад Panel; `frontend/panel/src/panel_shared/` — переиспользуемые Panel-компоненты и тема
- `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/e2e/` — тесты; `infra/{docker,clickhouse,prometheus,grafana}/` — инфраструктура; `scripts/` — служебные скрипты
- Контракты-источник истины: `specs/001-sputnik-data-portal/contracts/*.yaml`; профили запуска — `docker compose --profile <base|adv|demo> up`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Инициализация монорепозитория, инструментов качества и инфраструктурного каркаса

- [X] T001 Создать структуру монорепозитория: `services/*/src/`, `libs/*/src/`, `generators/sim/src/sim/`, `dags/`, `services/web-vitrina/src/web_vitrina/`, `frontend/panel/src/panel_shared/`, `tests/{unit,contract,integration,e2e}/`, `infra/{docker,clickhouse,prometheus,grafana}/`
- [X] T002 Инициализировать uv-workspace в `pyproject.toml` (Python 3.12, src-layout, workspace-члены `services/*`, `libs/*`, `generators/sim`) и зафиксировать `uv.lock`
- [X] T003 [P] Создать пакеты сервисов с `pyproject.toml` в `services/{web-vitrina,api-gateway,identity,catalog,order,review,delivery,sensor-gateway,ingestion,validation,transform,quality}/`
- [X] T004 [P] Создать пакеты библиотек с `pyproject.toml` в `libs/{contracts,db,observability,config}/`
- [X] T005 [P] Настроить ruff в `pyproject.toml` (target `py312`, line-length, набор правил)
- [X] T006 [P] Настроить black в `pyproject.toml` (line-length и target-версии)
- [X] T007 [P] Настроить mypy (strict, плагин pydantic) в `pyproject.toml`
- [X] T008 [P] Настроить pytest + pytest-asyncio (`asyncio_mode=auto`) в `pyproject.toml` и создать `tests/conftest.py`
- [X] T009 [P] Создать `.env.example` с переменными Postgres, Redis, Redpanda, ClickHouse, MongoDB, MinIO, Airflow
- [X] T010 [P] Создать `docker-compose.yml` с профилями `base`, `adv`, `demo`
- [X] T011 [P] Описать инфраструктурные сервисы compose (`postgres`, `redis`, `redpanda`, `minio`, `clickhouse`, `mongo`) с привязкой к профилям в `docker-compose.yml`
- [X] T012 [P] Создать multi-stage Dockerfile-ы сервисов в `infra/docker/`
- [X] T013 Создать GitHub Actions workflow `.github/workflows/ci.yml` со стадиями ruff, black, mypy, unit, contract, image build
- [X] T014 [P] Добавить в `.github/workflows/ci.yml` job контракт-линта OpenAPI/AsyncAPI из `specs/001-sputnik-data-portal/contracts/`
- [X] T015 [P] Создать `Makefile` с целями `up`, `down`, `lint`, `test`, `contract` для профилей `base`/`adv`/`demo`
- [X] T016 [P] Создать `README.md` с командой запуска одного профиля и описанием состава профилей
- [X] T017 [P] Настроить порог покрытия и артефакты покрытия в `.github/workflows/ci.yml`
- [X] T018 Создать skeleton-модули `__init__.py` и `main.py` для всех `services/*/src/<pkg>/`
- [X] T019 Зафиксировать workspace-зависимости `libs/*` в `pyproject.toml` сервисов

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Общие контракты, конфигурация, доступ к хранилищам, миграции и bootstrap — блокируют все истории

**⚠️ CRITICAL**: Ни одна пользовательская история не может начаться до завершения этой фазы

- [X] T020 [P] Реализовать Pydantic v2 модели каталога в `libs/contracts/src/contracts/catalog.py` из `openapi-catalog.yaml` (`Dataset`, `SchemaField`, `DatasetCategory` = `WEATHER|AIR_QUALITY|ENERGY|TRANSPORT|COMMERCE`, пагинация `{page,pageSize,total,totalPages,hasMore}`, конверт `{error:{code,message,requestId,details}}`)
- [X] T021 [P] Реализовать Pydantic v2 модели заказов в `libs/contracts/src/contracts/order.py` (`OrderStatus` = `ORDER_PENDING|ORDER_PAID|ORDER_FULFILLED|ORDER_CANCELLED`, `SubscriptionStatus` = `SUB_ACTIVE|SUB_PAUSED|SUB_CANCELLED`, `CreateOrderRequest`, `CreateSubscriptionRequest`)
- [X] T022 [P] Реализовать Pydantic v2 модели доставки в `libs/contracts/src/contracts/delivery.py` (`FileFormat` = `CSV|JSON|PARQUET`, схемы `429` + `Retry-After` и `403` для `X-Api-Key`)
- [X] T023 [P] Реализовать конверт и payload-ы событий commerce в `libs/contracts/src/contracts/events_commerce.py` (`{eventId,userId,productRef,at,payload}`, клик/заказ/подписка/скачивание/отзыв)
- [X] T024 [P] Реализовать события контента в `libs/contracts/src/contracts/events_content.py` (`SensorReadingPayload` с `readingId`, `stationId`, `measuredAt`, `receivedAt`; `DeadReading` с `reason` = `NULL_VALUE|OUT_OF_RANGE|SCHEMA_MISMATCH|DUPLICATE`)
- [X] T025 Собрать публичный экспорт контрактов в `libs/contracts/src/contracts/__init__.py` и скрипт сверки со спецификациями `scripts/contract_lint.py`
- [X] T026 [P] Unit-тесты сериализации и валидации контрактов в `tests/unit/libs/test_contracts.py`
- [X] T027 [P] Тесты перечислений (enum) и обязательных полей в `tests/unit/libs/test_enums.py`
- [X] T028 [P] Реализовать structlog JSON-логирование в `libs/observability/src/observability/logging.py`
- [X] T029 [P] Реализовать OpenTelemetry-трейсинг в `libs/observability/src/observability/tracing.py`
- [X] T030 [P] Реализовать prometheus-client метрики в `libs/observability/src/observability/metrics.py`
- [X] T031 Реализовать middleware сквозного `X-Request-Id` в `libs/observability/src/observability/request_id.py`
- [X] T032 [P] Unit-тесты observability в `tests/unit/libs/test_observability.py`
- [X] T033 [P] Реализовать базовые pydantic-settings в `libs/config/src/config/settings.py`
- [X] T034 [P] Реализовать настройки по компонентам (postgres/redis/kafka/clickhouse/mongo/minio) в `libs/config/src/config/components.py`
- [X] T035 [P] Unit-тесты конфигурации в `tests/unit/libs/test_config.py`
- [X] T036 [P] Реализовать async SQLAlchemy engine/session в `libs/db/src/db/postgres.py`
- [X] T037 [P] Реализовать Redis-клиент (rate-limit, идемпотентность) в `libs/db/src/db/redis.py`
- [X] T038 [P] Реализовать Kafka producer/consumer (aiokafka) в `libs/db/src/db/kafka.py`
- [X] T039 [P] Реализовать ClickHouse-клиент в `libs/db/src/db/clickhouse.py`
- [X] T040 [P] Реализовать Mongo-клиент (Motor) в `libs/db/src/db/mongo.py`
- [X] T041 [P] Реализовать S3/MinIO-клиент для lake/export в `libs/db/src/db/objectstore.py`
- [X] T042 Создать Alembic-каркас в `libs/db/alembic.ini` и `libs/db/migrations/env.py` с планом отката
- [X] T043 Миграция схемы `identity` (`users`, `pii_vault`, `api_keys`) в `libs/db/migrations/versions/0001_identity.py`
- [X] T044 Миграция схемы `catalog` (`providers`, `datasets`, `dataset_fields`) в `libs/db/migrations/versions/0002_catalog.py`
- [X] T045 Миграция схемы `orders` (`orders` с `UNIQUE(user_id, idempotency_key)`, `subscriptions`, `downloads`) в `libs/db/migrations/versions/0003_orders.py`
- [X] T046 Миграция схемы `reviews` (оценка `CHECK (rating BETWEEN 1 AND 5)`) в `libs/db/migrations/versions/0004_reviews.py`
- [X] T047 [P] Тесты миграций up/down в `tests/unit/db/test_migrations.py`
- [X] T048 Создать ClickHouse DDL `fact_readings` и `mv_readings_hourly` в `infra/clickhouse/01_fact_readings.sql`
- [X] T049 Создать ClickHouse DDL `mart_sales_daily`, `mart_quality_daily`, `mart_sentiment_daily` в `infra/clickhouse/02_marts.sql`
- [X] T050 [P] Создать индексы MongoDB `catalog_nosql.provider_meta` в `libs/db/src/db/mongo_indexes.py`
- [X] T051 [P] Реализовать bootstrap bucket/prefixes MinIO (`lake/`, `samples/`, `exports/`) в `libs/db/src/db/minio_bootstrap.py`
- [X] T052 Поднять локальный Airflow в `docker-compose.yml` и создать скелет `dags/` с `dags/.airflowignore`
- [X] T053 Создать seed предсозданных демонстрационных аккаунтов в `scripts/seed_demo_accounts.py`
- [X] T054 Связать профили `base|adv|demo` с сервисами и хранилищами в `docker-compose.yml`
- [X] T055 Foundational-интеграционные тесты стека (testcontainers) в `tests/integration/test_foundational_stack.py`

**Checkpoint**: Фундамент готов — истории можно реализовывать параллельно

---

## Phase 3: User Story 1 - Витрина данных, покупка и личный кабинет покупателя (Priority: P1) 🎯 MVP

**Goal**: Вход по демо-аккаунту, каталог с фильтрами и карточкой, покупка с идемпотентностью, скачивание только после оплаты, отзывы (в рейтинг идёт только последний), личный кабинет

**Independent Test**: Поднять стенд `docker compose --profile base up` и пройти путь «вход → каталог → карточка → покупка → скачивание → отзыв»; проверить отказ в скачивании без оплаты

### Tests for User Story 1

> **NOTE: Сначала написать тесты и убедиться, что они падают до реализации**

- [X] T056 [P] [US1] Контрактный тест identity (login, `/users/me`, API-ключи) в `tests/contract/test_identity.py`
- [X] T057 [P] [US1] Контрактный тест catalog (`listDatasets`, `getDataset`, `schema`, `sample`) в `tests/contract/test_catalog.py`
- [X] T058 [P] [US1] Контрактный тест order (`createOrder` идемпотентность, `listOrders`, подписки) в `tests/contract/test_order.py`
- [X] T059 [P] [US1] Контрактный тест delivery (отказ 403 без оплаты, формат выгрузки) в `tests/contract/test_delivery.py`
- [X] T060 [P] [US1] Контрактный тест review (оценка 1–5, последний отзыв в рейтинге) в `tests/contract/test_review.py`
- [X] T061 [P] [US1] Unit-тесты identity (аутентификация, выпуск/отзыв ключей) в `tests/unit/services/test_identity.py`
- [X] T062 [P] [US1] Unit-тесты catalog (фильтры `category`/`minQuality`, пагинация) в `tests/unit/services/test_catalog.py`
- [X] T063 [P] [US1] Unit-тесты order (идемпотентность `UNIQUE(user_id, idempotency_key)`) в `tests/unit/services/test_order.py`
- [X] T064 [P] [US1] Unit-тесты delivery (право скачивания по `ORDER_PAID|ORDER_FULFILLED`) в `tests/unit/services/test_delivery.py`
- [X] T065 [P] [US1] Unit-тесты review (`CHECK (rating BETWEEN 1 AND 5)`) в `tests/unit/services/test_review.py`
- [X] T066 [P] [US1] Интеграционный тест пути «вход→каталог→карточка→покупка→скачивание→отзыв» в `tests/integration/test_us1_journey.py`
- [X] T067 [P] [US1] Интеграционный тест отказа скачивания без оплаты в `tests/integration/test_us1_no_payment.py`
- [X] T068 [P] [US1] Интеграционный тест идемпотентности заказа (`UNIQUE(user_id, idempotency_key)`) в `tests/integration/test_us1_order_idempotency.py`

### Implementation for User Story 1

- [X] T069 [P] [US1] Реализовать репозитории `User`, `ApiKey`, `PiiVault` в `services/identity/src/identity/repository.py`
- [X] T070 [P] [US1] Реализовать сервис аутентификации (только предсозданные аккаунты, Bearer) в `services/identity/src/identity/service.py`
- [X] T071 [US1] Реализовать FastAPI identity (`POST /auth/login`, `GET /users/me`) в `services/identity/src/identity/main.py`
- [X] T072 [P] [US1] Реализовать выпуск и отзыв API-ключей в `services/identity/src/identity/api_keys.py`
- [X] T073 [P] [US1] Реализовать репозитории `Provider`, `Dataset`, `DatasetField` в `services/catalog/src/catalog/repository.py`
- [X] T074 [US1] Реализовать сервис каталога (фильтры `category`/`minQuality`, сортировка) в `services/catalog/src/catalog/service.py`
- [X] T075 [US1] Реализовать FastAPI catalog (`GET /datasets`, `/datasets/{datasetId}`, `/schema`, `/sample`) в `services/catalog/src/catalog/main.py`
- [X] T076 [P] [US1] Реализовать отдачу образца в `CSV|JSON|PARQUET` в `services/catalog/src/catalog/sample.py`
- [X] T077 [P] [US1] Реализовать репозиторий заказов и подписок в `services/order/src/order/repository.py`
- [X] T078 [US1] Реализовать создание заказа с идемпотентностью по `Idempotency-Key` в `services/order/src/order/service.py`
- [X] T079 [US1] Реализовать FastAPI order (`POST/GET /orders`, `POST /subscriptions`) в `services/order/src/order/main.py`
- [X] T080 [P] [US1] Реализовать публикацию `commerce.orders` и `commerce.subscriptions` в `services/order/src/order/events.py`
- [X] T081 [P] [US1] Реализовать репозиторий отзывов в `services/review/src/review/repository.py`
- [X] T082 [US1] Реализовать сервис отзывов (в рейтинг идёт только последний отзыв покупателя) в `services/review/src/review/service.py`
- [X] T083 [US1] Реализовать FastAPI review и публикацию `commerce.reviews` в `services/review/src/review/main.py`
- [X] T084 [P] [US1] Реализовать проверку права скачивания (`ORDER_PAID` или `ORDER_FULFILLED`) в `services/delivery/src/delivery/access.py`
- [X] T085 [US1] Реализовать выгрузку датасета (`CSV|JSON|PARQUET`, signed URL) в `services/delivery/src/delivery/service.py`
- [X] T086 [US1] Реализовать FastAPI delivery `GET /datasets/{datasetId}/download` в `services/delivery/src/delivery/main.py`
- [X] T087 [P] [US1] Реализовать запись истории скачиваний и событие `commerce.downloads` в `services/delivery/src/delivery/downloads.py`
- [X] T088 [US1] Реализовать api-gateway с маршрутизацией на identity/catalog/order/delivery/review в `services/api-gateway/src/api_gateway/main.py`
- [X] T089 [P] [US1] Реализовать Bearer-auth и `X-Api-Key` в `services/api-gateway/src/api_gateway/auth.py`
- [X] T090 [US1] Реализовать rate-limit `429` + `Retry-After` + `X-RateLimit-*` в `services/api-gateway/src/api_gateway/rate_limit.py`
- [X] T091 [P] [US1] Реализовать `X-Request-Id` и конверт `{error:{code,message,requestId,details}}` в `services/api-gateway/src/api_gateway/middleware.py`
- [X] T092 [P] [US1] Реализовать пагинацию `{page,pageSize,total,totalPages,hasMore}` в `services/api-gateway/src/api_gateway/pagination.py`
- [X] T093 [US1] Подключить Swagger/OpenAPI UI gateway в `services/api-gateway/src/api_gateway/openapi.py`
- [X] T094 [P] [US1] Реализовать Panel-страницу входа и каталога в `services/web-vitrina/src/web_vitrina/pages/catalog.py`
- [X] T095 [P] [US1] Реализовать Panel-карточку датасета со схемой полей в `services/web-vitrina/src/web_vitrina/pages/dataset.py`
- [X] T096 [P] [US1] Реализовать Panel-личный кабинет (заказы, подписки, скачивания) в `services/web-vitrina/src/web_vitrina/pages/account.py`
- [X] T097 [P] [US1] Реализовать Panel-форму отзыва в `services/web-vitrina/src/web_vitrina/components/review_form.py`
- [X] T098 [US1] Реализовать HTTP-клиент gateway на httpx в `services/web-vitrina/src/web_vitrina/api_client.py`
- [X] T099 [P] [US1] Реализовать общую Panel-тему и компоненты в `frontend/panel/src/panel_shared/theme.py`
- [X] T100 [US1] Наполнить профиль `base` готовыми датасетами через `generators/sim/src/sim/providers.py` и `generators/sim/src/sim/buyers.py`

**Checkpoint**: US1 полностью работоспособна и тестируема независимо на профиле `base`

---

## Phase 4: User Story 2 - Путь данных датчиков от источника до аналитической витрины (Priority: P2)

**Goal**: Приём чтений с `receivedAt` только на шлюзе, bronze → silver → gold, DLQ для битых записей, отчёт качества и восстановление после загрязнения

**Independent Test**: Запустить генератор с фиксированным `seed`, проследить чтения до витрины; применить `sim-dirty` и убедиться, что качество падает, а после очистки восстанавливается

### Tests for User Story 2

- [X] T101 [P] [US2] Контрактный тест событий `sensors.readings.v1` и `sensors.readings.dlq` в `tests/contract/test_content_events.py`
- [X] T102 [P] [US2] Unit-тест sensor-gateway (`receivedAt` проставляет только шлюз) в `tests/unit/services/test_sensor_gateway.py`
- [X] T103 [P] [US2] Unit-тест ingestion (bronze + DLQ с причиной) в `tests/unit/services/test_ingestion.py`
- [X] T104 [P] [US2] Unit-тест validation (silver без дублей и пропусков, Pandera-схемы) в `tests/unit/services/test_validation.py`
- [X] T105 [P] [US2] Unit-тест transform (gold-витрины, прогноз, тональность) в `tests/unit/services/test_transform.py`
- [X] T106 [P] [US2] Unit-тест quality-service (пересчёт `quality_score ∈ [0..1]`) в `tests/unit/services/test_quality.py`
- [X] T107 [P] [US2] Интеграционный тест bronze → silver → gold в `tests/integration/test_us2_content_pipeline.py`
- [X] T108 [P] [US2] Интеграционный тест DLQ (100% невалидных в DLQ, 0% в silver) в `tests/integration/test_us2_dlq.py`
- [X] T109 [P] [US2] Интеграционный тест деградации и восстановления качества в `tests/integration/test_us2_quality_degradation.py`
- [X] T110 [P] [US2] Интеграционный тест партнёрской выгрузки (CSV поставщика) в `tests/integration/test_us2_partner_export.py`

### Implementation for User Story 2

- [X] T111 [P] [US2] Реализовать приём чтений с проставлением `receivedAt` только шлюзом в `services/sensor-gateway/src/sensor_gateway/service.py`
- [X] T112 [US2] Реализовать FastAPI sensor-gateway `POST /readings` в `services/sensor-gateway/src/sensor_gateway/main.py`
- [X] T113 [P] [US2] Реализовать публикацию `sensors.readings.v1` с ключом `stationId` в `services/sensor-gateway/src/sensor_gateway/publisher.py`
- [X] T114 [US2] Реализовать ingestion Kafka → bronze (`lake/bronze/{provider}/{dt}`) в `services/ingestion/src/ingestion/consumer.py`
- [X] T115 [P] [US2] Реализовать публикацию битых записей в `sensors.readings.dlq` и архив `lake/dlq/{topic}/{dt}/part-*.ndjson` в `services/ingestion/src/ingestion/dlq.py`
- [X] T116 [US2] Реализовать validation bronze → silver с Pandera-схемами в `services/validation/src/validation/validator.py`
- [X] T117 [P] [US2] Реализовать Great Expectations отчёт `missing/dup/outlier/anomaly` в `lake/reports/quality/{dt}/report.json` в `services/validation/src/validation/quality_report.py`
- [X] T118 [US2] Реализовать transform silver → gold (агрегаты, прогноз, тональность) в `services/transform/src/transform/transform.py`
- [X] T119 [P] [US2] Реализовать загрузку `fact_readings` и `mv_readings_hourly` в ClickHouse в `services/transform/src/transform/gold_readings.py`
- [X] T120 [P] [US2] Реализовать загрузку `mart_quality_daily` в `services/transform/src/transform/gold_quality.py`
- [X] T121 [US2] Реализовать quality-service с пересчётом `qualityScore` в каталог в `services/quality/src/quality/service.py`
- [X] T122 [P] [US2] Реализовать FastAPI quality-service для Quality-page в `services/quality/src/quality/main.py`
- [X] T123 [P] [US2] Реализовать генератор `sim.sensors` (seed, станции, интервал, период) в `generators/sim/src/sim/sensors.py`
- [X] T124 [P] [US2] Реализовать генератор `sim.dirty` (доли пропусков/дублей/выбросов/битых) в `generators/sim/src/sim/dirty.py`
- [X] T125 [P] [US2] Реализовать CLI `sim` (seed, volume, period, профиль загрязнения) в `generators/sim/src/sim/cli.py`
- [X] T126 [US2] Реализовать DAG `ingest_readings` (`pull_bronze → validate → silver → transform → load_gold`) в `dags/ingest_readings.py`
- [X] T127 [P] [US2] Реализовать DAG `refresh_quality` с `retries`+backoff+сенсорами свежести в `dags/refresh_quality.py`
- [X] T128 [P] [US2] Реализовать DAG `sync_provider_exports` (`lake/partner/{provider}/{dt}.csv` → bronze → silver) в `dags/sync_provider_exports.py`
- [X] T129 [P] [US2] Реализовать идемпотентный upsert по детерминированным ключам/партициям в `services/validation/src/validation/idempotency.py`
- [X] T130 [P] [US2] Реализовать обработку пустого источника (корректные нулевые результаты без падения) в `services/validation/src/validation/empty_input.py`
- [X] T131 [US2] Включить sensor-gateway/ingestion/validation/transform/quality в профиль `adv` в `docker-compose.yml`
- [X] T132 [P] [US2] Реализовать Panel-страницу качества в `services/web-vitrina/src/web_vitrina/pages/quality.py`
- [X] T133 [US2] E2E-тест детерминизма генераторов по `seed` в `tests/e2e/test_seed_determinism.py`

**Checkpoint**: US1 и US2 работают независимо; данные датчиков доходят до gold-витрины

---

## Phase 5: User Story 3 - Подписка и живой поток свежих данных (Priority: P3)

**Goal**: Оформление подписки порождает событие, оркестрация доставляет свежие чтения по SSE с `id`=readingId, переподключение без дублей, корректные `PAUSED`/`CANCELLED`

**Independent Test**: Оформить подписку, подключиться к `GET /api/v1/streams/{subscriptionId}`, проверить уникальность `id` кадров и отсутствие дублей при переподключении

### Tests for User Story 3

- [X] T134 [P] [US3] Контрактный тест SSE `GET /streams/{subscriptionId}` в `tests/contract/test_stream_sse.py`
- [X] T135 [P] [US3] Unit-тест DAG `deliver_subscription` (выбор свежих чтений) в `tests/unit/dags/test_deliver_subscription.py`
- [X] T136 [P] [US3] Unit-тест SSE (`event: reading` с `id`=readingId, `event: ping`) в `tests/unit/services/test_delivery_sse.py`
- [X] T137 [P] [US3] Интеграционный тест «подписка → доставка → переподключение без дублей» в `tests/integration/test_us3_subscription_stream.py`
- [X] T138 [P] [US3] Интеграционный тест статусов `SUB_PAUSED`/`SUB_CANCELLED` в `tests/integration/test_us3_subscription_states.py`

### Implementation for User Story 3

- [X] T139 [P] [US3] Реализовать публикацию `commerce.clicks` из каталога в `services/catalog/src/catalog/clicks.py`
- [X] T140 [P] [US3] Реализовать публикацию `commerce.downloads` и `commerce.reviews` в `services/delivery/src/delivery/events.py`
- [X] T141 [US3] Реализовать DAG `deliver_subscription` (подписка → свежие чтения) в `dags/deliver_subscription.py`
- [X] T142 [US3] Реализовать SSE-эндпоинт `GET /streams/{subscriptionId}` в `services/delivery/src/delivery/streams.py`
- [X] T143 [P] [US3] Реализовать кадры `event: reading` с `id`=readingId и keep-alive `event: ping` в `services/delivery/src/delivery/sse.py`
- [X] T144 [P] [US3] Реализовать идемпотентность доставки (дедупликация по `readingId` в Redis) в `services/delivery/src/delivery/idempotency.py`
- [X] T145 [US3] Реализовать семантику `SUB_ACTIVE→SUB_PAUSED`, `SUB_PAUSED→SUB_ACTIVE`, `*→SUB_CANCELLED` в `services/order/src/order/subscription_states.py`
- [X] T146 [P] [US3] Реализовать остановку выборки новых данных при `SUB_PAUSED` в `dags/deliver_subscription.py`
- [X] T147 [P] [US3] Реализовать агрегацию `mart_sales_daily` в `services/transform/src/transform/gold_sales.py`
- [X] T148 [P] [US3] Реализовать агрегацию `mart_sentiment_daily` (тональность отзывов) в `services/transform/src/transform/gold_sentiment.py`
- [X] T149 [P] [US3] Реализовать SSE-клиент фасада на httpx-sse в `services/web-vitrina/src/web_vitrina/client_sse.py`
- [X] T150 [P] [US3] Реализовать Panel live-график потребления SSE в `services/web-vitrina/src/web_vitrina/pages/stream.py`
- [X] T151 [US3] Применить rate-limit `429` + `Retry-After` к SSE и выгрузке в `services/api-gateway/src/api_gateway/rate_limit.py`
- [X] T152 [US3] Включить Redpanda, Airflow, ClickHouse, MongoDB, MinIO в профиль `adv` в `docker-compose.yml`
- [X] T153 [US3] E2E-тест сквозного сценария подписки в `tests/e2e/test_us3_end_to_end.py`
- [X] T154 [P] [US3] Реализовать Panel-управление статусами подписки в `services/web-vitrina/src/web_vitrina/components/subscription_controls.py`
- [X] T155 [US3] Добавить runbook живого потока в `docs/runbooks/streams.md`

**Checkpoint**: Все пользовательские истории работоспособны независимо; сквозной SSE-сценарий проходит

---

## Phase 6: User Story 4 - Качество, наблюдаемость, безопасность и воспроизводимость (Priority: P4)

**Goal**: Алерты деградации, метрики лага/свежести, отсутствие PII в выгрузках, retention 12 месяцев, автоматические hard gates контрактов, детерминированный профиль `demo`

**Independent Test**: Искусственно ухудшить данные (алерт срабатывает), выборочно проверить выгрузку на отсутствие PII, повторить генерацию с тем же `seed` и сравнить результат

### Tests for User Story 4

- [X] T156 [P] [US4] Unit-тест метрик лага консьюмеров и свежести витрины в `tests/unit/observability/test_metrics.py`
- [X] T157 [P] [US4] Unit-тест маскирования PII в выгрузках (`***@domain`) в `tests/unit/test_pii_masking.py`
- [X] T158 [P] [US4] Интеграционный тест автоудаления PII по сроку 12 месяцев в `tests/integration/test_pii_retention.py`
- [X] T159 [P] [US4] Интеграционный тест сквозного `requestId` через несколько сервисов в `tests/integration/test_request_id_trace.py`
- [X] T160 [P] [US4] Schemathesis-сьют против живых сервисов в `tests/contract/test_schemathesis_catalog.py`
- [X] T161 [P] [US4] Тест hard gates контракт-линта (блокировка выпуска) в `tests/unit/test_ci_gates.py`
- [X] T162 [P] [US4] E2E-тест идентичности результата при одинаковом `seed` в `tests/e2e/test_determinism.py`
- [X] T163 [P] [US4] E2E-тест приёмки M0–M4 в `tests/e2e/test_acceptance_full.py`
- [X] T164 [P] [US4] Интеграционный тест срабатывания алерта при деградации в `tests/integration/test_alert_degradation.py`

### Implementation for User Story 4

- [X] T165 [P] [US4] Создать Prometheus scrape-конфиг в `infra/prometheus/prometheus.yml`
- [X] T166 [P] [US4] Реализовать метрики лага консьюмеров и свежести витрины в `services/quality/src/quality/metrics.py`
- [X] T167 [P] [US4] Создать Grafana-дашборд лага и свежести в `infra/grafana/dashboards/lag_freshness.json`
- [X] T168 [P] [US4] Настроить Grafana-алерт деградации в `infra/grafana/provisioning/alerting/degradation.yml`
- [X] T169 [US4] Реализовать application-level шифрование PII и ссылку `key_ref` в `services/identity/src/identity/pii.py`
- [X] T170 [P] [US4] Реализовать маскирование email/phone во всех выгрузках в `services/identity/src/identity/masking.py`
- [X] T171 [US4] Реализовать retention-job автоудаления PII по сроку (по умолчанию 12 месяцев) в `services/identity/src/identity/retention.py`
- [X] T172 [P] [US4] Реализовать сквозную передачу `X-Request-Id` во всех сервисах в `libs/observability/src/observability/request_id.py`
- [X] T173 [US4] Ужесточить CI-шлюзы (ruff/black/mypy/contracts/coverage) в `.github/workflows/ci.yml`
- [X] T174 [P] [US4] Реализовать подготовку предзаготовленных данных профиля `demo` в `scripts/prepare_demo_data.py`
- [X] T175 [P] [US4] Реализовать Panel Quality-dashboard с показателями деградации в `services/web-vitrina/src/web_vitrina/pages/quality_dashboard.py`

**Checkpoint**: Приёмка M0–M4 достижима на профиле `demo`

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Документация, очистка, производительность и финальная сверка приёмки

- [X] T176 [P] Обновить `README.md` разделами запуска, диагностики и состава профилей
- [X] T177 [P] Создать runbook конвейера данных в `docs/runbooks/pipeline.md`
- [X] T178 [P] Создать runbook DLQ и восстановления в `docs/runbooks/dlq.md`
- [X] T179 [P] Создать обзорную архитектурную схему в `docs/architecture/overview.md`
- [X] T180 Удалить дублирование и мёртвый код в `services/` и `libs/` (рефакторинг)
- [X] T181 [P] Оптимизировать запросы каталога и ClickHouse-витрин в `services/catalog/src/catalog/repository.py`
- [X] T182 [P] Унифицировать structlog-логи во всех сервисах `services/*/src/*/main.py`
- [X] T183 Проверить порог покрытия тестами и обновить настройки в `pyproject.toml`
- [X] T184 [P] Прогнать сценарии `quickstart.md` на профиле `base` и зафиксировать результат
- [X] T185 [P] Прогнать сценарии `quickstart.md` на профиле `adv` и зафиксировать результат
- [X] T186 [P] Прогнать сценарии `quickstart.md` на профиле `demo` и зафиксировать результат
- [X] T187 Сверить реализацию с `Docs/spec-kit/acceptance.md` по каждому сервису
- [X] T188 Сверить выполнение SC-001…SC-014 из `specs/001-sputnik-data-portal/spec.md`
- [X] T189 [P] Убрать отладочные выводы и временные файлы из `services/`, `libs/`, `generators/`
- [X] T190 Закрыть чек-листы задач и зафиксировать итоговый статус в `specs/001-sputnik-data-portal/tasks.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Зависимостей нет — можно начинать сразу
- **Foundational (Phase 2)**: Зависит от Phase 1 — БЛОКИРУЕТ все пользовательские истории
- **User Stories (Phase 3–6)**: Все зависят от Phase 2; далее могут идти параллельно или последовательно P1 → P2 → P3 → P4
- **Polish (Phase 7)**: Зависит от завершения нужных пользовательских историй

### User Story Dependencies

- **User Story 1 (P1)**: Стартует после Phase 2 — зависимостей от других историй нет (MVP, профиль `base`)
- **User Story 2 (P2)**: Стартует после Phase 2 — опирается на US1 для каталога/seed, но тестируется независимо (профиль `adv`)
- **User Story 3 (P3)**: Стартует после Phase 2 — использует US1 (подписки) и US2 (свежие чтения), но тестируется независимо
- **User Story 4 (P4)**: Стартует после Phase 2 — замыкает курс, зависит от артефактов US1–US3 для сквозной приёмки

### Within Each User Story

- Тесты (контрактные, unit, интеграционные) пишутся и ПАДАЮТ до реализации
- Модели/репозитории — до сервисов; сервисы — до эндпоинтов; core — до интеграции
- История завершается до перехода к следующему приоритету

### Parallel Opportunities

- Все задачи Setup с `[P]` — параллельно
- Все Foundational с `[P]` — параллельно внутри Phase 2
- После Phase 2 истории US1–US4 можно вести параллельно
- Все тесты одной истории с `[P]` — параллельно
- Репозитории и модели внутри истории с `[P]` — параллельно
- Сервисы разных историй могут разрабатываться разными исполнителями

---

## Parallel Example: User Story 1

```bash
# Запустить все контрактные тесты US1 параллельно:
Task: "Контрактный тест identity в tests/contract/test_identity.py"
Task: "Контрактный тест catalog в tests/contract/test_catalog.py"
Task: "Контрактный тест order в tests/contract/test_order.py"
Task: "Контрактный тест delivery в tests/contract/test_delivery.py"

# Запустить независимые репозитории US1 параллельно:
Task: "Репозитории User/ApiKey/PiiVault в services/identity/src/identity/repository.py"
Task: "Репозитории Provider/Dataset/DatasetField в services/catalog/src/catalog/repository.py"
Task: "Репозиторий заказов и подписок в services/order/src/order/repository.py"
Task: "Репозиторий отзывов в services/review/src/review/repository.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Завершить Phase 1: Setup
2. Завершить Phase 2: Foundational (КРИТИЧНО — блокирует истории)
3. Завершить Phase 3: User Story 1
4. **STOP и VALIDATE**: проверить US1 независимо на профиле `base`
5. Демонстрировать готовый MVP

### Incremental Delivery

1. Setup + Foundational → фундамент готов
2. US1 → независимая проверка → демо (MVP)
3. US2 → независимая проверка → демо (профиль `adv`)
4. US3 → независимая проверка → демо (живой поток)
5. US4 → независимая проверка → сводный прогон (профиль `demo`)
6. Каждая история добавляет ценность, не ломая предыдущие

### Parallel Team Strategy

1. Команда совместно завершает Setup + Foundational
2. После фундамента:
   - Исполнитель A: User Story 1
   - Исполнитель B: User Story 2
   - Исполнитель C: User Story 3
   - Исполнитель D: User Story 4
3. Истории завершаются и интегрируются независимо

---

## Notes

- `[P]` — задачи в разных файлах без взаимных зависимостей
- Метка истории обеспечивает трассировку задачи к пользовательской истории
- Тесты обязательны (Конституция, Принцип V) и пишутся до реализации
- Каждая история независимо завершаема и тестируема
- Проверять падение тестов до реализации
- Останавливаться на checkpoints для независимой валидации историй
- Избегать расплывчатых задач, конфликтов по одному файлу и кросс-историйных зависимостей, ломающих независимость
- Инварианты для сверки: `UNIQUE(user_id, idempotency_key)`, `CHECK (rating BETWEEN 1 AND 5)`, `ORDER_PENDING|ORDER_PAID|ORDER_FULFILLED|ORDER_CANCELLED`, `SUB_ACTIVE|SUB_PAUSED|SUB_CANCELLED`, `WEATHER|AIR_QUALITY|ENERGY|TRANSPORT|COMMERCE`, `receivedAt` только sensor-gateway, пагинация `{page,pageSize,total,totalPages,hasMore}`, конверт `{error:{code,message,requestId,details}}`, `X-Api-Key` на download/stream, `429`+`Retry-After`, SSE `event: reading` с `id`=readingId

---

## Итоговый статус (T190, 2026-09-18)

- **Открытых задач: 0** — все T001–T190 отмечены `[X]`.
- **Шлюзы:** `ruff check` — OK; `ruff format --check` — 234 файла; `black --check` —
  188 файлов; `mypy` — success (188 файлов); `contract_lint` — 5/5 контрактов;
  `pytest -q` — **230 passed, 0 failed, 0 skipped**; покрытие — **80.65%**
  (порог 80%, `[tool.coverage.report] fail_under`).
- **Профили:** `docker-compose --profile base|adv|demo config -q` — OK. Все
  образы профилей на месте; `base` перепроверен live: login → каталог/пагинация
  → 403 без оплаты → идемпотентный заказ → выгрузка CSV/JSON 200 → рейтинг =
  последний отзыв → конверт ошибки с `requestId`. `adv` — приём партии
  (accepted=17, dead=1) → bronze + `lake/dlq/...` → silver + `report.json` →
  `transform` Exit 0 → ClickHouse gold. `demo` — `prepare_demo_data` (datasets=5,
  buyers=3, readings=144, partners=5) идемпотентно (повтор даёт те же счётчики).
- **Исправления в рамках полировки:** добавлен сервис `migrate` (Alembic до
  старта сервисов/seed), смонтирован `infra/clickhouse` в
  `/docker-entrypoint-initdb.d`, `libs/db` копируется в runtime-образ.
  В `transform` исправлены: обработка `pd.NaT` в `_as_utc` (иначе падение
  вставки `received_at` в ClickHouse) и дедупликация `load_gold_readings` по дню
  факта, а не по дате прогона (иначе повторные прогоны плодили дубли, SC-005).
- **Сверка приёмки:** `docs/acceptance-report.md` (acceptance.md по сервисам и
  SC-001…SC-014).
- **Ограничение среды:** полный оркестрированный прогон Airflow M0–M4 в среде
  сверки не запускался из-за заполненного docker-root `/srv` (98–100%);
  его логика покрыта `tests/e2e/test_acceptance_full.py` и integration-тестами
  testcontainers. Сценарии `adv`/`demo` проверены прямым запуском слоёв.
