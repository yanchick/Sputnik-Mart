# TODO — SputnikMart / «Спутник Данные»

## Статус проекта
- Фича: `001-sputnik-data-portal` — демо-портал маркетплейса данных.
- Задачи: 190 из 190 выполнено (`specs/001-sputnik-data-portal/tasks.md`).
- Тесты: 326 passed, 0 failed, 0 skipped.
- Покрытие: 81.30% (порог 80).
- Гейты зелёные: ruff, ruff format, black, mypy, contract_lint (8 контрактов), docker-compose профили base/adv/demo.
- Репозиторий НЕ является git-репозиторием.

## Что уже сделано
- Фаза 1 Setup (T001–T019): uv-монорепо, тулинг, docker-compose профили, CI-скелет, contract-lint.
- Фаза 2 Foundational (T020–T055): `libs/*` (contracts, db, observability, config), Alembic-миграции Postgres, DDL ClickHouse, MongoDB, MinIO, Airflow, сиды демо-аккаунтов.
- Фаза 3 US1 MVP (T056–T100): identity/catalog/order/review/delivery + api-gateway + Panel-витрина, профиль `base`.
- Фаза 4 US2 (T101–T133): sensor-gateway → ingestion(+DLQ) → validation → transform → quality, генераторы sim, DAGи, профиль `adv`.
- Фаза 5 US3 (T134–T155): commerce-события, `deliver_subscription`, SSE-поток, PAUSED/CANCELLED, марты.
- Фаза 6 US4 (T156–T175): метрики лага/свежести, Grafana, PII-маскировка/ретеншн, requestId, CI-гейты, schemathesis, профиль `demo`.
- Фаза 7 Polish (T176–T190): README/рунбуки, живая проверка quickstart на всех профилях, отчёт `docs/acceptance-report.md`.

## Открытые задачи (для продолжения)
1. Дождаться/получить результат финального независимого ревью реализации (делегация `profitable-moccasin-puma`); устранить Critical/Major, если появятся.
2. Полный прогон M0–M4 под Airflow не выполнялся: на docker-хосте мало места (корень `/srv` ~98%, свободно ~2.6 ГБ). Освободить место и прогнать `dags/` под Airflow.
3. Живой SSE-поток вручную не проверялся (покрыт `tests/integration/test_us3_subscription_stream.py`) — при желании проверить вручную.
4. Порты 9000/8080 заняты посторонними контейнерами; для `adv`/`demo` использовался временный compose-override из `/tmp` (в репозиторий не вносился). Учесть при следующем запуске.
5. 72 теста без pytest-маркеров — проставить маркеры (`unit`/`contract`/`integration`/`e2e`), чтобы `-m` работал корректно (необязательно).
6. Расхождение формулировки T140: T140 упоминает `commerce.reviews` в `delivery/events.py`, но по AsyncAPI продюсер отзывов живёт в `services/review/src/review/events.py` (намеренно не дублировался).
7. Опционально: в таблице стека конституции нет строки про фронтенд (Panel); при желании добавить через `/speckit.constitution`.
8. Мелочи из design-ревью (не блокирующие): неиспользуемый `ApiKeyAuth` в catalog/order; формулировка числа сервисов; голые статусы `ACTIVE/PAUSED/CANCELLED` в прозе spec; неоднозначность FR-036 (создание подписки vs потребление потока); необъявленные `X-RateLimit-*` заголовки в OpenAPI.
9. Перед коммитом убрать временный Sync Impact Report из `.specify/memory/constitution.md`.
10. Репозиторий не под git: при необходимости `git init` и первый коммит.

## Результаты финального ревью реализации (2026-09-18)
Вердикт: CHANGES-REQUIRED по итогам ДВУХ независимых ревью (Critical — нет; Major — 6 + 2 = 8; Minor — 6 + 9 = 15).

### Major
- [x] M1 (FR-019/FR-025): бизнес-марты `mart_sales_daily` и `mart_sentiment_daily` не наполняются в рантайме — нет Kafka-консьюмера для `commerce.*`; `transform_batch` вызывается с пустыми `reviews/orders/downloads` (`services/transform/src/transform/main.py:67`, `transform.py:29-30`). Прогноз пишется в `gold/staging/.../forecasts.ndjson`, но не загружается в ClickHouse (`dags/ingest_readings.py:107-153`). Нужно: консьюмер commerce-событий → transform, и загрузка прогноза в gold. — Исправлено: консьюмер `transform.commerce_consumer` (compose-сервис `commerce-transform`, adv) дедуплицирует `commerce.*` по `eventId` и грузит `mart_*`; добавлена таблица `forecasts` и её загрузка в `_load_gold`.
- [x] M2 (FR-037/SC-013): ретеншн PII реализован, но не запланирован — `delete_expired_pii`/`run_retention_job` (`services/identity/src/identity/retention.py:52-74`) не вызываются нигде вне тестов. Нужно: DAG/крон/startup-хук. — Исправлено: ежедневный DAG `retention_pii` + разовый compose-сервис `retention` в профиле `adv` (`identity.retention.main`).
- [x] M3 (FR-026/SC-007/SC-011): метрики лага и свежести определены, но не публикуются — `publish_consumer_lag`/`publish_data_freshness` (`services/quality/src/quality/metrics.py:52-71`) не имеют вызовов в проде. Дашборд `lag_freshness` без живого источника. — Исправлено: `quality.runtime_metrics` заполняет лаг/свежесть из `fact_readings`/каталога; `/metrics` и DAG `refresh_quality` публикуют их.
- [x] M4 (security): неаутентифицированный write-эндпоинт `POST /api/v1/quality/recalculate` (`services/quality/src/quality/main.py:134-142`) пишет `catalog.datasets.quality_score`; порт 8007 проброшен наружу (`docker-compose.yml:437-438`). Нужно: закрыть авторизацией или убрать из публичного доступа. — Исправлено: `require_operator` требует валидный Bearer/`X-Api-Key` (иначе 401); порт 8007 не публикуется, вход через gateway.
- [x] M5 (Constitution Principle I): нет OpenAPI для identity, review, quality REST (`/auth/login`, `/users/me`, api-keys, `/reviews`, `/datasets/{id}/rating`, `/quality*`) — нет авторитетного контракта, не входят в merged gateway OpenAPI (`services/api-gateway/src/api_gateway/openapi.py:10`). Нужно: добавить контракты либо оформить явное исключение в конституции. — Исправлено: добавлены `openapi-identity.yaml`, `openapi-review.yaml`, `openapi-quality.yaml`, подключены к merged OpenAPI gateway; contract_lint 8/8; новые schemathesis-тесты `tests/contract/test_schemathesis_{identity,review,quality}.py`.
- [x] M6 (data-model ownership): межсервисный прямой доступ к таблицам: identity читает `orders.subscriptions` (`services/identity/.../repository.py:131-140`), order читает `catalog.datasets` (`services/order/.../repository.py:155-161`), delivery читает `orders.orders` и `identity.api_keys` (`services/delivery/.../access.py:15-48`), quality пишет `catalog.datasets` (`services/quality/.../service.py:63-70`). Нужно: либо перевести на API/события, либо задокументировать как осознанное отклонение. — Исправлено: все четыре переведены на API владельца через общий клиент `libs/service-client` (`HttpServiceClient`, `SERVICE_URL_*`): identity→order `GET /subscriptions`, order→catalog `GET /datasets/{id}`, delivery→order/identity/catalog (`/orders/access`, `/api-keys/resolve`, `/datasets/{id}/schema`, `/subscriptions/{id}`, `/orders/fulfill`), quality→catalog `POST /datasets/quality-scores` (operator-auth). Контракты и `data-model.md` обновлены; два оставшихся отклонения (delivery пишет `orders.downloads`; quality read-only читает `catalog.datasets`) задокументированы.

### Minor
- [x] m7: sensor-gateway публикует в DLQ (`services/sensor-gateway/.../main.py:73,90`), что противоречит `contracts/README.md:33` и `asyncapi-content.yaml:8` (DLQ от ingestion/validation). — Исправлено: `sensor-gateway` объявлен продюсером `sensors.readings.dlq` в `asyncapi-content.yaml`, обновлены `contracts/README.md` и `docs/runbooks/dlq.md`; тест `test_sensor_gateway_is_a_dlq_producer`.
- [x] m8: текст отзывов не фильтруется по PII перед записью (`services/review/.../service.py:41-48`), хотя `data-model.md:182` это требует. — Исправлено: `mask_text` применяется до записи и в payload `commerce.reviews`/ответе; тесты `test_create_review_scrubs_pii_before_persistence`, `test_review_payload_and_event_are_scrubbed`, `test_review_text_is_scrubbed_end_to_end`.
- [x] m9: `SchemaField.ordinal` (`libs/contracts/.../catalog.py:56`) отсутствует в `openapi-catalog.yaml:216-232`; contract_lint не ловит лишние поля ответа. — Исправлено: `ordinal` объявлен в `openapi-catalog.yaml`; contract_lint сверяет модель↔контракт в обе стороны.
- [x] m10: unit-Job в CI (`ci.yml:56`, `-m unit`) пропускает тесты без маркера (`tests/unit/libs/test_config.py`, `test_observability.py`, `test_contracts.py`, `test_enums.py`, `tests/unit/db/test_migrations.py`). — Исправлено: `pytestmark = pytest.mark.unit` добавлен во все 10 файлов; `-m unit` собирает 183 теста.
- [x] m11: `dags/` исключён из покрытия (`ci.yml:72-75`, `pyproject.toml:168`) — оркестрация не влияет на порог 80%. — Исправлено: исключение зафиксировано явно и обосновано комментариями в `pyproject.toml` (`[tool.coverage.run]`) и `ci.yml` (Airflow не в dev-зависимостях; чистая логика вынесена в services/libs, DAGи покрыты unit-тестами и e2e).
- [x] m12: машина состояний заказа используется частично — заказы сразу `ORDER_PAID` (`services/order/.../service.py:66`), переходы `ORDER_PENDING`/`ORDER_FULFILLED` недостижимы; нет симуляции оплаты. — Исправлено: заказ создаётся `ORDER_PENDING`, добавлены `POST /orders/{orderId}/pay` и `/orders/fulfill`, скачивание → `ORDER_FULFILLED`, демо-автооплата `demo_auto_pay`; тесты `order_states` и `tests/integration/test_m6_ownership.py`.

### Второе независимое ревью реализации (2026-09-18)

Вердикт: CHANGES-REQUIRED (Critical — нет; Major — 2; Minor — 9).

#### Major
- [x] QR-1. Страница качества не работает (FR-021, SC-008): `services/quality/src/quality/main.py:107-110` отдаёт `snapshot.__dict__` в snake_case (`dataset_id`, `quality_score`, `missing_rate`, `dup_rate`, `outlier_rate`, `anomalies_cnt`), а `services/web-vitrina/src/web_vitrina/pages/quality.py:20-28,51-57` читает camelCase (`datasetId`, `name`, `qualityScore`, `missingRate`, `dupRate`, `outlierRate`, `anomaliesCnt`) — все значения `None`. Плюс списочный endpoint `services/quality/src/quality/service.py:77-100` жёстко ставит ставки/аномалии в `0.0` и не сливает отчёт валидации (это делает только `quality/main.py:112-132`). `docs/acceptance-report.md:49` переоценивает доказательство SC-008. — Исправлено: единый camelCase-контракт (`snapshot_payload`), list-эндпоинт сливает отчёт validation.
- [x] QR-2. Страница качества недоступна из рантайма (FR-021, SC-008) : `pages/quality.py:19` по умолчанию `QUALITY_URL=http://localhost:8007`; в `docker-compose.yml:386-398` для `web-vitrina` задан только `GATEWAY_URL`; в `services/api-gateway/src/api_gateway/main.py:54-75` нет маршрута `/quality`. Итог: вкладка «Качество» (`web_vitrina/main.py:36`) показывает ошибку загрузки во всех профилях; теста на это нет (`tests/e2e/test_acceptance_full.py:60`). — Исправлено: маршрут `/api/v1/quality` в gateway, Panel ходит через `GATEWAY_URL`, quality добавлен в `base`; тесты `test_api_gateway.py`.

#### Minor
- [x] QR-3. 10 unit-файлов без `pytestmark = pytest.mark.unit`, поэтому `pytest tests/unit -m unit` (`ci.yml:56`) их пропускает (в coverage-джобе они всё же гоняются). — Исправлено: маркер добавлен во все 10 файлов (`tests/unit -m unit` — 183 passed).
- [x] QR-4. Мёртвая константа `MACHINE_PREFIXES` (`api_gateway/auth.py:14`). — Удалена.
- [x] QR-5. Некорректный JSON даёт 500: `sensor-gateway/main.py:68` `await request.json()` уходит мимо обработчика (ожидается 400). — Исправлено: битый JSON → 400 `BAD_REQUEST` в едином конверте.
- [x] QR-6. Гейтвей пробрасывает только `content-type`/`content-disposition` (`api_gateway/main.py:78-80`), теряя `Retry-After` и др. — Исправлено: пробрасываются `Retry-After` и `X-RateLimit-*`.
- [x] QR-7. Странный tuple-payload `(key, payload, key)` в `sensor_gateway/publisher.py:41`. — Исправлено: `NullPublisher` хранит чистый `(key, payload)`; тест `test_publisher_emits_clean_two_tuple_payload`.
- [x] QR-8. TTL дедупликации ingestion 24 ч (`ingestion/consumer.py:57`) — нет документированной границы для FR-015. — Задокументировано в `research.md` и `docs/runbooks/pipeline.md`; тест `test_redis_dedup_ttl_bound_is_24h`.
- [x] QR-9. `docs/acceptance-report.md:43` утверждает smoke «через gateway», но `tests/e2e/test_acceptance_full.py:154-192` дергает сервисы напрямую. — Исправлено: SC-002/SC-008 в отчёте приведены в соответствие с реальными тестами.
- [x] QR-10. Демо-гигиена секретов: `.env` совпадает с `.env.example`; `DEFAULT_PII_KEY` захардкожен (`libs/observability/src/observability/pii.py:16`, переопределяется env). — Добавлен `.gitignore` (`.env`, `.env.*`, `!.env.example`), `.env.example` предупреждает о демо-значениях и содержит `AUTH_SECRET`; `DEFAULT_PII_KEY` помечен как демо-only; тест `test_env_secret_hygiene`.
- [x] QR-11. `specs/001-sputnik-data-portal/spec.md:7` всё ещё `Status: Draft` после реализации. — Исправлено: статус переведён в `Implemented` (единственная изменённая строка спеки).

Также оба ревью подтверждают: FR-011 (receivedAt только в sensor-gateway), асинхронность (Constitution II), contract-first + `release-gate`, идемпотентность на всех слоях, PII-изоляция/ретеншн — реализованы корректно; FR-021 — единственный провал в таблице FR.

Положительное (проверено): единые конвенции ошибок/пагинации/429/SSE, реальная идемпотентность (UNIQUE + SET NX + upsert), receivedAt только в sensor-gateway, детерминизм генераторов, CI-гейт `release-gate`, нет skip/xfail/TODO/FIXME.

## Как продолжить
- Прочитать: `specs/001-sputnik-data-portal/{spec.md,plan.md,tasks.md,data-model.md,quickstart.md}`, `docs/acceptance-report.md`, `Docs/spec-kit/acceptance.md`.
- Установить зависимости: `uv sync --all-packages --dev`.
- Прогнать тесты: `uv run pytest -q` (покрытие: `uv run pytest -q --cov`).
- Поднять стенд: `docker compose --profile base up -d` (или `adv` / `demo`).
- Следующие возможные команды Spec Kit: `/speckit.analyze`, `/speckit.checklist`.
