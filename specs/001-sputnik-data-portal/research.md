# Phase 0 — Research: Демо-портал «Спутник Данные»

Технические решения для фичи `001-sputnik-data-portal`. Большинство открытых вопросов ТЗ §13 закрыты ADR пакета `Docs/spec-kit/adr/`; вопрос синхронизации с «Семинары — Сквозной пайплайн» не покрыт ни одним ADR и остаётся открытым (отложен до отдельного решения). Рабочие копии контрактов в `specs/001-sputnik-data-portal/contracts/` авторитетны и расширены относительно `Docs/specs/` (`X-Api-Key`, `429` + `Retry-After`, пагинация `{page, pageSize, total, totalPages, hasMore}`). Источники: ТЗ «Демо-портал маркетплейса данных (SDD)», конституция `.specify/memory/constitution.md`, ADR-0001…ADR-0006.

### Бренд и единая легенда

- **Decision**: Использовать бренд «Спутник Данные» (`Sputnik Data`) во всех спецификациях, заголовках `info.title` и текстах курса.
- **Rationale**: Бренд влияет на `info.title` всех OpenAPI/AsyncAPI, нейминг и материалы курса; поздняя смена дорога (ADR-0001). «Спутник Данные» отражает и commerce-нить маркетплейса, и наследован от исходной концепции «Спутник Маркет».
- **Alternatives considered**: «СенсорХаб» — акцентирует только content-нить (датчики) и хуже подходит базовому уровню, поэтому отклонён (ADR-0001).

### Архитектура монорепозитория (contract-first)

- **Decision**: Один монорепозиторий, где `specs/001-sputnik-data-portal/contracts/*.yaml` — источник истины, `services/<name>/src/<pkg>/` — реализация, `libs/` — общие модели/БД/наблюдаемость/config, `dags/` — Airflow, `generators/sim/` — генераторы, `frontend/panel/` — Panel-компоненты.
- **Rationale**: Модель SDD требует править контракт до кода, а CI — блокировать несовместимость; каждый сервис получает пару «спека + папка кода», а один репозиторий обслуживает оба уровня курса (ADR-0005, README пакета спецификаций).
- **Alternatives considered**: Полирепозиторий на сервис — усложняет кросс-сервисные правки контрактов и единый CI; инлайн-скрипты генераторов вместо пакета — дублируются и не переиспользуются студентами (отвергнуто в ADR-0002).

### Декомпозиция на сервисы и инфраструктуру

- **Decision**: 13 сервисов — `web-vitrina`, `api-gateway`, `identity`, `catalog`, `order`, `review`, `delivery`, `sensor-gateway`, `ingestion`, `validation`, `transform`, `quality`, `orchestration` (Airflow); 6 инфраструктурных компонентов — PostgreSQL, ClickHouse, MongoDB (`catalog-nosql`), MinIO (`data-lake`), Redis, Redpanda (`event-bus`), плюс observability (Prometheus/Grafana) как опциональный.
- **Rationale**: Реестр §3 ТЗ и паспорта §3.1 фиксируют единственного владельца данных на сервис; межсервисный доступ — только через API/события, не через прямой SQL к чужой схеме (§7.1). Такая гранулярность позволяет независимо продемонстрировать каждую тему курса (API, события, озеро, витрины, качество, оркестрация).
- **Alternatives considered**: Монолит с модулями — не даёт «путешествия события» по микросервисам и не покрывает темы семинаров; разделение на ещё более мелкие функции — избыточно для демо-масштаба.

### Шина событий, топики, ключи и retention

- **Decision**: Обязательная Kafka-совместимая шина — Redpanda (Kafka API). Топики: `sensors.readings.v1` (ключ `stationId`, retention 7d), `sensors.readings.dlq` (ключ `stationId`, 30d), `commerce.clicks` (ключ `datasetId`, 7d), `commerce.orders`/`commerce.subscriptions`/`commerce.downloads`/`commerce.reviews` (ключи `orderId`/`subscriptionId`/`downloadId`/`reviewId`, 30d).
- **Rationale**: Redpanda полностью покрывает асинхронные нити курса через Kafka API, включая DLQ, и снижает число сервисов в compose; ключи партиций сохраняют порядок по одной станции/продукту (ADR-0004, §7.1.5 ТЗ, event-conventions).
- **Alternatives considered**: NATS JetStream — лёгкий, но оставлен опциональным флагом продвинутой практики сравнения шин, а не обязательной шиной (ADR-0004); exactly-once-семантика — не используется, так как корректность строится на идемпотентности.

### At-least-once и идемпотентность по идентификатору

- **Decision**: Модель доставки at-least-once; каждый консьюмер идемпотентен по `readingId`/`eventId`; ключи дедупликации хранятся в Redis; запись в слои идемпотентна через upsert по детерминированным ключам/партициям; `UNIQUE (user_id, idempotency_key)` для заказов.
- **Граница дедупликации (FR-015)**: ключи `ingestion` живут в Redis с TTL 24 ч (`RedisDeduplicator`, `ttl_seconds=86_400`, `services/ingestion/src/ingestion/consumer.py`). Повтор в пределах суток отбрасывается как `DUPLICATE`; более поздний повтор может быть обработан снова, но безусловная идемпотентность записи в слои (upsert) не даёт дублей в silver/gold.
- **Rationale**: At-least-once неизбежно даёт повторную доставку, поэтому корректность опирается на идемпотентность, а не на иллюзию exactly-once (конституция, принцип IV; §7.2 «Сквозные инварианты потоков»). Это закрывает FR-006, FR-015, FR-023, FR-024 и SC-005.
- **Alternatives considered**: Exactly-once-транзакции Kafka — сложны и не покрывают идемпотентность DAG-перезапусков; дедупликация только в памяти консьюмера — теряется при рестарте.

### Политика DLQ

- **Decision**: DLQ обязательна для обеих нитей: битые записи уходят в `sensors.readings.dlq` с указанием причины; архив — `lake/dlq/{topic}/{dt}/part-*.ndjson`; «ядовитые» сообщения после исчерпания ретраев — в DLQ.
- **Rationale**: Неконформные записи не должны попадать в следующий слой (конституция, принцип III; FR-012, FR-016); DLQ — обязательный инвариант потоков и часть ключевого сценария `sim-dirty` (ТЗ §7.2, §7.1.4).
- **Alternatives considered**: «Тихий» пропуск битых записей — нарушает 0%-требование SC-004 и лишает студента материала для разбора; карантин только в объектном хранилище без топика — теряется связь с причиной и возможность переигрывания.

### Транспорт живого потока (SSE)

- **Decision**: Живой поток — Server-Sent Events (`text/event-stream`) на `GET /api/v1/streams/{subscriptionId}`; событие `event: reading` с `id = readingId`, keep-alive — `event: ping`.
- **Rationale**: SSE — one-way сервер→клиент поверх обычного HTTP, автоматически переподключается и тривиален для Panel и ноутбуков; идемпотентность обеспечивается полем `id` (ADR-0003, FR-022, FR-023).
- **Alternatives considered**: WebSocket — полнодуплекс и сложнее на клиенте/в auth для базового уровня; оставлен как опциональная продвинутая практика профиля `adv` (ADR-0003).

### Медальон-слои и gold-витрины ClickHouse

- **Decision**: bronze — MinIO `lake/bronze/{provider}/{dt}` (иммутабельное сырьё, Parquet/NDJSON); silver — MinIO `lake/silver/{dataset}/{dt}` (после валидации, без дублей/пропусков); gold — ClickHouse `fact_readings` + `mv_readings_hourly` и `mart_sales_daily`/`mart_quality_daily`/`mart_sentiment_daily`; двигатели MergeTree, партиционирование по дате, MV для метрик.
- **Rationale**: Переход между слоями возможен только после успешной валидации (конституция, принцип III; FR-014, FR-017, FR-018, FR-019); ClickHouse даёт быстрые аналитические агрегаты, MV пересчитывают часовые метрики автоматически (§7.1.3 ТЗ).
- **Alternatives considered**: Хранение gold в Parquet-файлах — нет SQL-аналитики и MV; витрины в Postgres — не предназначены для аналитической нагрузки демо-агрегатов.

### Контроль качества: Pandera + Great Expectations

- **Decision**: Схемы слоёв описываются Pandera; проверки аномалий и отчёты — Great Expectations; отчёт (`missing/dup/outlier/anomaly`) пишется в `lake/reports/quality/{dt}/report.json` и `mart_quality_daily`, после чего `quality-service` пересчитывает `qualityScore`.
- **Rationale**: Контроль на границах слоёв не позволяет дефектным данным просочиться в аналитику (конституция, принцип III; FR-017, FR-020, FR-021). «Пустые данные не ломают прогон» и детерминированный отчёт по `seed` — инвариант `validation-service`.
- **Alternatives considered**: Только ручные ассерты в трансформациях — не дают воспроизводимого отчёта и видимости на Quality-page; только Great Expectations без Pandera — теряется типизация схем на входе.

### Дизайн Airflow DAGов

- **Decision**: Четыре DAGа — `ingest_readings` (`pull_bronze → validate → silver → transform → load_gold`), `deliver_subscription` (по событию `commerce.subscriptions` выбирает свежие чтения и отдаёт в SSE), `refresh_quality` (пересчёт `qualityScore` и Quality-page), `sync_provider_exports` (партнёрские CSV → bronze → silver). Обязательны `retries` + backoff + `on_failure_callback` и сенсоры свежести.
- **Rationale**: §8 ТЗ и паспорт `orchestration` фиксируют состав DAGов и требования идемпотентности; повторный запуск не создаёт дублей (FR-024, FR-033), а сенсоры гарантируют свежесть витрины.
- **Alternatives considered**: Планировщик внутри каждого сервиса (cron/asyncio) — нет единого UI прогонов, ретраев и сенсоров; Celery beat — не покрывает сенсоры и lineage, ожидаемые в курсе.

### Детерминированный пакет генераторов `sim`

- **Decision**: Отдельный Python-пакет `sim` с единым CLI: `sim.sensors`, `sim.providers`, `sim.buyers`, `sim.dirty`; параметры — seed, объём/период/интервал, профиль «загрязнения»; форматы выдачи — JSON-строки в Kafka и CSV/JSON/Parquet в MinIO.
- **Rationale**: Одинаковый `seed` даёт идентичный датасет (FR-029, SC-003); пакет переиспользуется сервисами, студенческими ноутбуками и практиками очистки; `sim-dirty` отдельным флагом портит bronze и не мешает обычному прогону (ADR-0002, §6 ТЗ).
- **Alternatives considered**: Инлайн-скрипты внутри сервисов — дублирование между `sensor-gateway`, `catalog`, `sim-buyers` и практиками, сложность переиспользования (ADR-0002).

### Профили запуска Docker Compose

- **Decision**: Три профиля: `base` — фасад (`web-vitrina`, `api-gateway`, `catalog`, `identity`, `order`, `delivery`, Postgres, генератор готовых датасетов); `adv` — полный стек (base + content plane, event-bus, Airflow, ClickHouse, MinIO, Mongo); `demo` — как `adv`, но с предзаготовленным репозиторием данных.
- **Rationale**: Профили управляются env/compose-overlay, а не кодом (ADR-0005); `base` закрывает базовый уровень за ≤ 5 минут (SC-001), `adv`/`demo` — продвинутый и сводный прогон (FR-030, SC-010).
- **Alternatives considered**: Один монолитный compose без профилей — тяжёл для студентов базового уровня; отдельные репозитории под профили — дублирование контрактов и кода.

### Фронтенд на Python + Panel

- **Decision**: `web-vitrina` — Panel (HoloViz) поверх Bokeh: `FastListTemplate` (каркас), `Tabulator` (таблицы), `hvPlot`/`ECharts` (графики), `param` (состояние), `panel.auth` (вход), `httpx` + `httpx-sse` (REST и SSE). Фасад общается только с `api-gateway`.
- **Rationale**: Единый язык на всём стеке убирает вторую JS-сборку и дублирование типов, ускоряет выход на рабочий портал; SSE читается серверной стороной и пушится в Bokeh-виджет (ADR-0006). Фасад заменяем и изолирован за gateway.
- **Alternatives considered**: React + Vite + TS — индустриальный стандарт, но второй toolchain без учебной выгоды; Dash (Plotly) — Plotly-центричен и менее гибок в вёрстке витрины (ADR-0006).

### Наблюдаемость (логи, трассировка, метрики, алерты)

- **Decision**: structlog со сквозным `requestId` (заголовок `X-Request-Id`), OpenTelemetry для трассировки, prometheus-client для метрик, дашборды и алерты Grafana; обязательные метрики — лаг консьюмеров и свежесть данных/витрины.
- **Rationale**: Без сквозной наблюдаемости невозможны отладка распределённого контура и доверие к данным (конституция, принцип V); FR-026, FR-027, SC-011, SC-012 требуют связи логов и алерта при деградации.
- **Alternatives considered**: Неструктурные логи и только stdout — не позволяют связать сервисы по `requestId`; только APM без Prometheus — не даёт метрик лага/свежести в Grafana.

### PII: изоляция, маскирование и срок хранения

- **Decision**: PII хранится только в `identity.pii_vault` (application-level шифрование, ссылка на KMS `key_ref`); email/телефон маскируются во всех выгрузках; срок хранения фиксированный (по умолчанию 12 месяцев) с автоматическим удалением; отдельный сценарий удаления по запросу не реализуется.
- **Rationale**: Конституция и §9 ТЗ требуют исключить PII из аналитики и выгрузок; SC-009, SC-013 и FR-028, FR-037 задают проверяемые критерии; уточнение Q3 фиксирует retention без ad-hoc удаления.
- **Alternatives considered**: PII в общих таблицах с маскированием «на чтении» — риск утечки в витрины и выгрузки; удаление по запросу — вне заявленного объёма работ (spec.md Clarifications).

### Ограничение частоты запросов (rate-limit)

- **Decision**: Gateway применяет rate-limit к аутентифицированному покупателю и к машинному ключу ко всем операциям с данными, включая выгрузку и живой поток; значения по умолчанию настраиваемы; при превышении — `429 RATE_LIMITED` с `Retry-After` и заголовками `X-RateLimit-*`.
- **Rationale**: Конституция, принцип IV (лимиты в Redis) и api-conventions задают заголовки и код ошибки; FR-038 и SC-014 требуют отказа с указанием времени повторной попытки.
- **Alternatives considered**: Лимиты только на уровне reverse-proxy — не различают покупателя и машинный ключ; отсутствие лимитов на SSE — неконтролируемое потребление долгоживущих соединений.

### Контрактные и интеграционные тесты

- **Decision**: unit — pytest/pytest-asyncio; интеграционные — testcontainers с реальными Postgres/Redis/ClickHouse/Redpanda/MinIO; контрактные — schemathesis против живых сервисов; проверка OpenAPI/AsyncAPI-линтерами в CI; схемы БД — через Alembic с планом отката.
- **Rationale**: Конституция (принцип V, «Рабочий процесс и шлюзы качества») и FR-031 требуют машинной проверки контрактов и блокировки выпуска при провале; SC-005 проверяется идемпотентными прогонами.
- **Alternatives considered**: Мокать инфраструктуру в интеграционных тестах — теряется проверка реальной семантики Kafka/ClickHouse/Postgres; контрактные тесты только по спекам без живого сервиса — не ловят расхождения реализации.

### Соглашения API и событий

- **Decision**: REST — версия в пути `/api/v1`, camelCase, UTC ISO-8601, единый конверт ошибок с `requestId`, пагинация-обёртка `{ data, pagination }`, auth Bearer/`X-Api-Key`; события — единый конверт `{ eventId, userId, productRef, at, payload }`, версия схемы в имени топика. Уточнение: в машинных AsyncAPI-контрактах `EventEnvelope` определён как `{ eventId, userId, at }`, а поля топика разворачиваются рядом через `allOf`; `productRef` и вложенный `payload` — описательные понятия, не отдельные wire-поля (`productRef` соответствует плоскому `datasetId`).
- **Rationale**: Единые правила исключают рассинхрон между сервисами, генераторами и DAGами и делают интеграцию проверяемой машинно (конституция, принцип I; FR-034).
- **Alternatives considered**: Snake_case в JSON и разнобой форматов ошибок — усложняют клиентов и контрактные тесты; конверт без `eventId` — ломает идемпотентность потребителей.
