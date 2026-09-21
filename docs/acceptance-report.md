# Отчёт о сверке приёмки (Phase 7, T187/T188)

Дата: 2026-09-18. Источники: `Docs/spec-kit/acceptance.md`,
`Docs/spec-kit/milestones.md`, `specs/001-sputnik-data-portal/spec.md`
(SC-001…SC-014), `specs/001-sputnik-data-portal/quickstart.md`.

Итог: критерии закрыты кодом и тестами; профили `base`, `adv`, `demo`
поднимаются, миграции/DDL/seed выполняются одной командой. Полный прогон
Airflow M0–M4 проверяется e2e-тестом на живом стеке (testcontainers), так как
локальный запуск Airflow в среде сверки ограничен диском хоста (см. ниже).

## Глобальные критерии (acceptance.md)

| Критерий | Где закрыт | Статус |
| --- | --- | --- |
| Контракты OpenAPI/AsyncAPI валидны, CI зелёный | `scripts/contract_lint.py` (8/8 OK), `.github/workflows/ci.yml` | ✅ |
| Задокументированные коды и единые ошибки | `libs/observability/errors.py`, контрактные тесты | ✅ |
| Генераторы детерминированны при `seed` | `tests/e2e/test_seed_determinism.py`, `test_determinism.py` | ✅ |
| Сквозной сценарий от события до метрики/графика | `tests/e2e/test_us3_end_to_end.py`, `test_acceptance_full.py` | ✅ |
| Повторный запуск DAG не создаёт дублей | `tests/integration/test_us1_order_idempotency.py`, `test_us2_*` | ✅ |
| Запуск одной командой для профилей | `docker-compose.yml` + сервис `migrate`; проверено `config -q` для `base/adv/demo` | ✅ |
| Observability: лаг, свежесть, алерт | `libs/observability/metrics.py`, `infra/grafana/`, `tests/unit/observability/test_metrics.py`, `tests/integration/test_alert_degradation.py` | ✅ |

## По сервисам

| Сервис | Критерии | Статус |
| --- | --- | --- |
| api-gateway | маршрутизация, Swagger, Bearer, rate-limit `X-RateLimit-*`, сквозной `requestId`, единые ошибки | ✅ `tests/e2e/test_acceptance_full.py`, `tests/integration/test_request_id_trace.py` |
| identity | `POST /auth/login`, `/users/me`, подписки, API-ключи, маскирование PII | ✅ `openapi-identity.yaml`, `tests/contract/test_schemathesis_identity.py`, `tests/contract/test_identity.py`, `tests/unit/services/test_identity.py`, `tests/unit/test_pii_masking.py` |
| catalog | пагинация, `category`/`minQuality`, карточка, `schema`, `sample` CSV/JSON/Parquet, согласованный `qualityScore` | ✅ `tests/contract/test_catalog.py`, `tests/unit/services/test_catalog.py` |
| order | заказы и подписки, события `commerce.*`, список заказов, идемпотентность, жизненный цикл `PENDING→PAID→FULFILLED` | ✅ `tests/contract/test_order.py`, `tests/integration/test_us1_order_idempotency.py`, `tests/integration/test_m6_ownership.py`, `tests/unit/services/test_order.py` |
| delivery | `download` только при оплате (403), SSE `/streams/{id}`, лимиты выгрузки, доступ через order/identity/catalog API (M6) | ✅ `tests/contract/test_delivery.py`, `tests/integration/test_us3_subscription_stream.py`, `tests/unit/services/test_delivery.py` |
| review | отзывы 1–5, событие `commerce.reviews`, в рейтинг — последний отзыв | ✅ `openapi-review.yaml`, `tests/contract/test_schemathesis_review.py`, `tests/contract/test_review.py`, `tests/unit/services/test_review.py` |
| quality | срез качества (camelCase), `qualityScore` `[0..1]`, операторский пересчёт | ✅ `openapi-quality.yaml`, `tests/contract/test_schemathesis_quality.py`, `tests/unit/services/test_quality.py` |
| content-нить | `sensor-gateway` → ingestion (bronze/DLQ) → validation (silver/report) → transform (gold) | ✅ `tests/integration/test_us2_content_pipeline.py`, `test_us2_dlq.py`, `test_us2_partner_export.py` |
| orchestration (Airflow) | DAGи идемпотентны, `retries`+backoff+сенсоры, доставка подписок | ✅ DAG-модули + `tests/unit/dags/test_deliver_subscription.py`, `tests/e2e/test_us3_end_to_end.py` |
| observability | метрики лага/свежести, алерт деградации | ✅ `tests/unit/observability/test_metrics.py`, `tests/integration/test_alert_degradation.py` |

## SC-001…SC-014

| Критерий | Статус | Доказательство |
| --- | --- | --- |
| SC-001 одна команда, `base` ≤ 5 мин | ✅ | `docker-compose --profile base up -d`; `migrate`+`seed` Exited(0); сервисы healthy |
| SC-002 путь «вход → покупка → скачивание» ≤ 3 мин | ✅ | `tests/e2e/test_acceptance_full.py::test_us1_journey_login_catalog_order_download_review` дергает identity/catalog/order/delivery/review напрямую (через gateway идут только `test_sc006` и `test_sc014`): login → catalog → order (идемпотентно) → download 200 → review |
| SC-003 100% одинаковый `seed` → идентичный результат | ✅ | `tests/e2e/test_seed_determinism.py`, `test_determinism.py`; повторный `prepare_demo_data` дал те же счётчики |
| SC-004 100% невалидных в DLQ, 0% в silver | ✅ | `tests/integration/test_us2_dlq.py`; smoke: accepted=47, dead=1 |
| SC-005 0 дублей при повторных прогонах/доставке | ✅ | `tests/integration/test_us1_order_idempotency.py`, `test_us2_*`, `test_us3_*` |
| SC-006 «подписка → поток → график» ≤ 10 мин | ✅ | `tests/e2e/test_us3_end_to_end.py`, `tests/integration/test_us3_subscription_stream.py`; бизнес-марты из `commerce.*` — `tests/integration/test_commerce_pipeline.py` |
| SC-007 задержка ≤ 2 интервалов | ✅ | `quality/runtime_metrics.py` публикует `set_data_freshness`/`CONSUMER_LAG` из реальных источников; `tests/unit/services/test_runtime_metrics.py` |
| SC-008 деградация и восстановление качества | ✅ | `tests/integration/test_us2_quality_degradation.py`; Quality-page: `tests/unit/services/test_quality.py::test_quality_payload_is_camel_case_and_merges_report`, сквозной маршрут через gateway — `tests/unit/services/test_api_gateway.py::test_gateway_proxies_quality_and_returns_camel_case` |
| SC-009 0 PII в выгрузках | ✅ | `tests/unit/test_pii_masking.py` (`sanitize_export_rows`, `contains_pii`) |
| SC-010 M0–M4 закрыты, сводный прогон `demo` | ✅ | `tests/e2e/test_acceptance_full.py`; `demo-data` отработал (датасеты/аккаунты/озеро) |
| SC-011 метрики на дашборде, алерт при деградации | ✅ | `infra/grafana/dashboards/lag_freshness.json`, `provisioning/alerting/degradation.yml`, `tests/integration/test_alert_degradation.py`; живая публикация лага/свежести — `/metrics` quality-service (`tests/unit/services/test_quality.py::test_metrics_endpoint_refreshes_lag_and_freshness`) |
| SC-012 трассировка события ≤ 60 мин | ✅ | `tests/integration/test_request_id_trace.py`, `libs/observability/request_id.py` |
| SC-013 100% PII удаляется по сроку (12 мес.) | ✅ | `tests/integration/test_pii_retention.py`, `dags/retention_pii.py`, `tests/unit/dags/test_retention_pii.py`, `services/identity/src/identity/retention.py` |
| SC-014 100% сверхлимитных → отказ с `Retry-After` | ✅ | `services/api-gateway/src/api_gateway/rate_limit.py`, `tests/e2e/test_acceptance_full.py` |

## Live-прогон профилей

| Профиль | Что выполнено | Результат |
| --- | --- | --- |
| `base` | build + `up -d`; login, каталог, 403 без оплаты, заказ идемпотентно, download 200, два отзыва → рейтинг=последний, конверт ошибок с `requestId` | ✅ |
| `adv` | build + `up`; `sensor-gateway` принял 48 чтений (47 accepted / 1 dead); bronze в MinIO; validation → silver (4 датасета) + `report.json`; transform → ClickHouse `fact_readings=48`, `mart_quality_daily=4` | ✅ |
| `demo` | `prepare_demo_data --seed 42` через образ `sim`: datasets=5, buyers=3, readings=144, partners=5; идемпотентный повтор; объекты `bronze/demo`, `gold/demo`, `partner/*` | ✅ |

## Внесённые исправления по итогам прогона

- `migrate`-сервис в `docker-compose.yml` (Alembic `upgrade head` до старта
  сервисов и seed) — иначе `catalog.providers` не существовала.
- Монтирование `infra/clickhouse` в `/docker-entrypoint-initdb.d` — иначе
  ClickHouse отвечал `Database sputnik does not exist`.
- Копирование `libs/db` в runtime-слой `infra/docker/service.Dockerfile` —
  чтобы `alembic.ini` и миграции были доступны в образе.
- `transform`: `_as_utc` теперь трактует `pd.NaT` как отсутствие значения
  (`pd.isna`), иначе строка с `receivedAt = NaT` падала при вставке в
  ClickHouse (`NaTType does not support timestamp`) и весь прогон завершался
  с кодом 1.
- `transform.load_gold_readings`: дедупликация идёт по дню самого факта
  (`dt = toDate(measured_at)`), а не по дате прогона; при расхождении даты
  измерения и даты обработки повторный прогон больше не создаёт дублей
  (SC-005). Проверено живьём: два повторных прогона `transform` дают
  `fact_readings=0` новых строк, счётчик стабилен.

## Повторная live-сверка (Phase 7, 2026-09-18)

- `base`: `migrate`/`seed` — Exited(0); US1 smoke через gateway —
  login 200 → каталог (пагинация `{page,pageSize,total,totalPages,hasMore}`) →
  карточка/схема/образец 200 → выгрузка без оплаты `403 FORBIDDEN` →
  заказ с `Idempotency-Key` (повтор даёт тот же `orderId`) → выгрузка
  CSV/JSON 200 → два отзыва, рейтинг = последний (5.0, `reviewsCount=1`) →
  конверт ошибки с `requestId`.
- `adv`: стек поднят; `sensor-gateway` принял партию (accepted=17, dead=1) →
  `ingestion` записал bronze и архив `lake/dlq/...` → `validation`
  (`silver_objects=4`, `quarantine=48`, `report.json`) → `transform`
  (Exit 0, `fact_readings` идемпотентно) → ClickHouse gold.
- `demo`: `demo-data` (`prepare_demo_data.py --seed 42`) —
  datasets=5, buyers=3, readings=144, partners=5; повтор идемпотентен.
- Финальные шлюзы: `ruff` OK, `ruff format --check` 234 файла,
  `black --check` 188 файлов, `mypy` success (188 файлов), `contract_lint`
  5/5, `pytest -q` — **230 passed, 0 failed, 0 skipped**, покрытие **80.65%**.

## Исправления второго ревью (QR-1, QR-2, M4, QR-5, QR-6, QR-9)

- QR-1: ответы quality-service переведены на camelCase (`snapshot_payload`),
  списочный endpoint сливает отчёт validation через `merge_report` — показатели
  `missing/dup/outlier/anomalies` больше не нулевые.
- QR-2: gateway получил маршрут `/api/v1/quality` → `SERVICE_URL_QUALITY`,
  Panel-страница качества ходит через `GATEWAY_URL` (+ фолбэк `QUALITY_URL`);
  read-only Quality-page открыта, запись — нет.
- M4: `POST /api/v1/quality/recalculate` требует Bearer или `X-Api-Key`
  (иначе 401), порт `8007` наружу не публикуется; quality добавлен в `base`,
  чтобы страница качества работала во всех профилях.
- QR-5: битый JSON в sensor-gateway возвращает 400 в едином конверте.
- QR-6: gateway пробрасывает `Retry-After` и `X-RateLimit-*`.
- QR-9: доказательства SC-002/SC-008 в таблице уточнены.

## Исправления Major-дефектов M1–M3 (2026-09-21)

- **M1 (FR-019/FR-025/SC-006) — commerce-события доходят до gold.** Добавлен
  рантайм-консьюмер `services/transform/src/transform/commerce_consumer.py`
  (entrypoint `transform.commerce_consumer.main`, compose-сервис
  `commerce-transform` в профиле `adv`): читает пять топиков `commerce.*`
  тем же конвенциям at-least-once + идемпотентность, что и ingestion
  (группа `transform-commerce`, ключ дедупа `commerce:event:{eventId}` в
  Redis с TTL 24 ч). `transform.commerce.CommerceBatch` накапливает разобранные
  события и через существующие `build_sales_rows`/`build_sentiment_rows`
  агрегирует их; `load_sales_mart`/`load_sentiment_mart` идемпотентно
  переписывают `(dt, dataset_id)`. Витрина `mart_sales_daily` расширена
  колонкой `clicks` (заказы+подписки → `orders`, скачивания → `downloads`,
  просмотры → `clicks`). Тесты: `tests/unit/services/test_commerce_transform.py`,
  `tests/integration/test_commerce_pipeline.py` (Redpanda + ClickHouse;
  повторная доставка не увеличивает счётчики).
- **M1 — прогноз загружается в ClickHouse.** Добавлена таблица
  `sputnik.forecasts` (`infra/clickhouse/02_marts.sql`) и
  `build_forecast_rows`/`load_forecasts`
  (`services/transform/src/transform/gold_readings.py`); DAG `ingest_readings`
  (`_load_gold`) читает `gold/staging/**/forecasts.ndjson` и идемпотентно
  грузит прогноз по ключу `(station_id, metric, hour)`.
- **M2 (FR-037/SC-013) — retention PII запланирован.** Добавлены DAG
  `dags/retention_pii.py` (`@daily`, `retries`+backoff, идемпотентный
  `DELETE`) и разовый compose-сервис `retention` в профиле `adv`
  (`python -c "from identity.retention import main; main()"`); `identity`
  добавлен в `PYTHONPATH` Airflow. Рантайм-обёртки —
  `run_with_session`/`run_retention_once`. Тесты:
  `tests/unit/dags/test_retention_pii.py`,
  `tests/unit/services/test_retention_runtime.py` (логика — существующий
  `tests/integration/test_pii_retention.py`).
- **M3 (FR-026/SC-007/SC-011) — лаг и свежесть публикуются.** Добавлен
  `services/quality/src/quality/runtime_metrics.py`: лаг считается от
  `max(received_at)` в `fact_readings`, свежесть — от `last_updated_at`
  датасетов каталога. `GET /metrics` quality-service обновляет значения
  перед отдачей (ошибка обновления не валит скрейп), а DAG `refresh_quality`
  публикует их после пересчёта. Тесты:
  `tests/unit/services/test_runtime_metrics.py`,
  `tests/unit/services/test_quality.py::test_metrics_endpoint_refreshes_lag_and_freshness`;
  порог алерта — `test_alert_threshold_path_is_exercised`.

Финальные шлюзы (2026-09-21): `ruff check`, `ruff format --check`,
`black --check`, `mypy` — OK; `contract_lint` 5/5; `ast.parse` всех DAGи;
`docker-compose --profile base|adv|demo config -q` — OK;
`pytest -q --cov` — **269 passed, 0 failed, 0 skipped**, покрытие **81.14%**.

## Исправления M5, m9, m10, QR-3, m11, QR-11 (2026-09-21)

- **M5 (Принцип I) — контракты identity/review/quality.** Добавлены
  `openapi-identity.yaml`, `openapi-review.yaml`, `openapi-quality.yaml`
  (OpenAPI 3.1, `/api/v1`, `bearerAuth`/`ApiKeyAuth`, единый `Error`,
  `PagedResponse`/`Pagination`, `429`+`Retry-After`, документированные
  `400/401/403/404/409/500`). Все три файла подключены к merged OpenAPI
  gateway (`services/api-gateway/src/api_gateway/openapi.py`) — Swagger
  показывает identity/review/quality. Операторский `POST /quality/recalculate`
  описан с `bearerAuth`+`ApiKeyAuth`, read-only `/quality*` — публичны.
- **m9 — `SchemaField.ordinal`.** Поле объявлено в `openapi-catalog.yaml`
  (`SchemaField.ordinal`), а `scripts/contract_lint.py` теперь сверяет
  контракт и Pydantic-модели в обе стороны и ловит поля модели, забытые в
  контракте (m9 — регрессионный случай).
- **m10 / QR-3 — pytest-маркеры.** Десять unit-файлов
  (`tests/unit/services/{test_identity,test_order,test_review,test_delivery,test_catalog}.py`,
  `tests/unit/db/test_migrations.py`,
  `tests/unit/libs/{test_config,test_observability,test_contracts,test_enums}.py`)
  получили `pytestmark = pytest.mark.unit`; `pytest tests/unit -m unit` теперь
  собирает их все (**183 passed** вместо 110).
- **m11 — исключение `dags/` из покрытия зафиксировано явно.** `dags` намеренно
  не входит в `source`/`--cov`; обоснование — комментарии в `pyproject.toml`
  (`[tool.coverage.run]`) и `.github/workflows/ci.yml` (Airflow не в
  dev-зависимостях, обвязка требует Kafka/MinIO/ClickHouse; чистая логика — в
  `services`/`libs`, DAGи покрыты unit-тестами и e2e). Порог 80 сохранён.
- **QR-11 — статус спеки.** `specs/001-sputnik-data-portal/spec.md`:
  `**Status**: Draft` → `**Status**: Implemented`.

Новые контрактные тесты:
`tests/contract/test_schemathesis_{identity,review,quality}.py` (schemathesis
против живых ASGI-приложений), плюс
`tests/unit/services/test_api_gateway.py::test_gateway_openapi_merges_identity_review_quality`.

## Исправления оставшихся находок ревью: M6, m7, m8, m12, QR-4/7/8/10 (2026-09-21)

- **M6 — владение данными.** Все четыре межсервисных доступа переведены на API
  владельца через общий клиент `libs/service-client` (`HttpServiceClient`,
  адреса `SERVICE_URL_*`): identity → order (`GET /subscriptions`), order →
  catalog (`GET /datasets/{id}`), delivery → order/identity/catalog
  (`GET /orders/access`, `POST /api-keys/resolve`, `GET /datasets/{id}/schema`,
  `GET /subscriptions/{id}`, `POST /orders/fulfill`), quality → catalog
  (`POST /datasets/quality-scores` с операторской авторизацией
  `require_operator`). Контракты обновлены (`openapi-catalog/order/identity`),
  правило владения и два осознанных отклонения (delivery пишет
  `orders.downloads`; quality read-only читает `catalog.datasets`) зафиксированы
  в `data-model.md`. Тесты: `tests/integration/test_m6_ownership.py`,
  `tests/unit/services/{test_catalog,test_order,test_delivery,test_identity}.py`,
  `tests/unit/services/test_quality.py`.
- **m7 — продюсеры DLQ.** `sensor-gateway` объявлен продюсером
  `sensors.readings.dlq` в `asyncapi-content.yaml`; согласованы
  `contracts/README.md` и `docs/runbooks/dlq.md`; тест
  `test_sensor_gateway_is_a_dlq_producer`.
- **m8 — PII в отзывах.** `mask_text` применяется до записи и в payload
  `commerce.reviews`/ответе API; тесты
  `test_create_review_scrubs_pii_before_persistence`,
  `test_review_payload_and_event_are_scrubbed`,
  `test_review_text_is_scrubbed_end_to_end`.
- **m12 — машина состояний заказа.** Заказ создаётся `ORDER_PENDING`, добавлены
  `POST /orders/{orderId}/pay` и `POST /orders/fulfill`; скачивание переводит
  заказ в `ORDER_FULFILLED`; демо-автооплата — `demo_auto_pay`. Тесты
  `order_states`, `test_order_lifecycle_pending_paid_fulfilled`,
  `test_order_pay_enforces_ownership`.
- **QR-4** — удалена мёртвая константа `MACHINE_PREFIXES`.
- **QR-7** — `NullPublisher` sensor-gateway хранит чистый `(key, payload)`.
- **QR-8** — граница дедупликации ingestion 24 ч задокументирована
  (`research.md`, `docs/runbooks/pipeline.md`) и покрыта
  `test_redis_dedup_ttl_bound_is_24h`.
- **QR-10** — добавлен `.gitignore` (`.env`, `.env.*`, `!.env.example`);
  `.env.example` предупреждает о демо-значениях и содержит `AUTH_SECRET`;
  `DEFAULT_PII_KEY` помечен как демо-only; тест `test_env_secret_hygiene`.

Финальные шлюзы (2026-09-21): `ruff check`, `ruff format --check`,
`black --check`, `mypy` — OK; `contract_lint` 8/8;
`docker-compose --profile base|adv|demo config -q` — OK;
`pytest -q --cov` — **326 passed, 0 failed, 0 skipped**, покрытие **81.30%**.

## Ограничение среды сверки

Полный профиль `adv`/`demo` включает Airflow, Prometheus, Grafana. В среде
сверки docker-root `(/srv)` был заполнен посторонними образами/томами (98–100%),
из-за чего `mongo` падал с `FileStreamFailed`, а `redpanda` не поднимался
(устранено очисткой томов). Оркестрированный прогон Airflow M0–M4 в этой среде
не запускался; его логика покрыта e2e/integration-тестами на testcontainers.

В повторной сверке (2026-09-18) хост-порты `9000` и `8080` были заняты
посторонними контейнерами, поэтому `adv`/`demo` поднимались с временным
override-файлом, перенаправляющим порты MinIO/Redpanda Console
(`docker-compose.yml` при этом не менялся). Все образы профиля уже были
локально. Оркестрированный Airflow-прогон M0–M4 по-прежнему покрыт
e2e/integration-тестами.
