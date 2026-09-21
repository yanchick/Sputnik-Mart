# Phase 1 — Модель данных: Демо-портал «Спутник Данные»

Логическая модель сущностей фичи `001-sputnik-data-portal`, правила валидации, переходы состояний и отображение на физические хранилища. Соглашения: camelCase в контрактах, snake_case в колонках БД, идентификаторы вида `{prefix}_{...}`, время UTC ISO-8601, float64. Каждый сервис — единственный владелец своих таблиц; межсервисный доступ — только через API/события владельца (ТЗ §7.1). Ссылки на требования — FR/SC из [spec.md](./spec.md).

## Межсервисное взаимодействие (владение данными)

Общий клиент `libs/service-client` (`HttpServiceClient`, адреса из `SERVICE_URL_*`, как в api-gateway) — единственная точка исходящих HTTP-вызовов между сервисами. После ревью M6:

- `identity` читает подписки покупателя через `GET /api/v1/subscriptions` order-сервиса (владелец `orders.subscriptions`), а не прямым SQL;
- `order` получает цену датасета через `GET /api/v1/datasets/{datasetId}` каталога; отдаёт delivery `GET /orders/access`, `GET /subscriptions/{subscriptionId}`, `POST /orders/fulfill`;
- `delivery` разрешает `X-Api-Key` через `POST /api/v1/api-keys/resolve` identity, читает схему через `GET /api/v1/datasets/{datasetId}/schema` каталога и проверяет оплату через order-API;
- `quality` пишет `qualityScore` через внутренний `POST /api/v1/datasets/quality-scores` каталога (операторская авторизация `require_operator`), владельца `catalog.datasets`; прямых записей в чужие таблицы нет.

**Осознанные отклонения (демо).** Остаются два прямых доступа, не входившие в перечень M6 и сохранённые ради устойчивости демо; они не влияют на целостность критичных данных и явно зафиксированы здесь:

- `delivery` пишет факт выгрузки в `orders.downloads` (`services/delivery/src/delivery/downloads.py`) — история скачиваний ведётся рядом с заказом; вынос в order-API вынесен в потенциальные улучшения;
- `quality` читает `catalog.datasets` для read-only проекции Quality-page и метрик свежести (`services/quality/src/quality/service.py`, `runtime_metrics.py`); запись в каталог — только через catalog-API выше.

## Общие соглашения

- **Идентификаторы**: `us_` (покупатель), `ak_` (API-ключ), `pv_` (провайдер), `ds_` (датасет), `od_` (заказ), `sub_` (подписка), `dl_` (скачивание), `rv_` (отзыв), `rd_` (чтение), `ev_` (событие), `req_` (requestId).
- **Время**: все метки в UTC ISO-8601; в БД — `TIMESTAMPTZ`; в ClickHouse — `DateTime64(3)`.
- **Деньги**: `NUMERIC(12,2)`, валюта по умолчанию `RUB`.
- **Удаление PII**: фиксированный срок хранения (по умолчанию 12 месяцев) с автоматическим удалением; отдельный сценарий удаления по запросу не реализуется (FR-037, SC-013).

## Покупатель (User)

Пользователь портала; владеет заказами, подписками, скачиваниями и отзывами. Регистрация самостоятельная не поддерживается — только предсозданные демонстрационные аккаунты (FR-001).

| Поле | Тип | Правила |
| --- | --- | --- |
| `user_id` | TEXT PK | `us_...`, неизменяем |
| `display_name` | TEXT NOT NULL | отображаемое имя |
| `status` | TEXT NOT NULL | `ACTIVE` \| `BLOCKED`, по умолчанию `ACTIVE` |
| `created_at` | TIMESTAMPTZ NOT NULL | default `now()` |

**Связи**: 1:N с `Order`, `Subscription`, `Download`, `Review`, `ApiKey`; 1:1 с `PiiVault`.
**Валидация**: `status` только из перечисления; вход — по предсозданным учётным данным (FR-001).
**Переходы**: `ACTIVE → BLOCKED` (административно); обратный переход допустим.

## Хранилище PII (PiiVault)

Изолированное хранилище персональных данных, не участвующее в аналитических витринах (FR-028, FR-037).

| Поле | Тип | Правила |
| --- | --- | --- |
| `user_id` | TEXT PK/FK → `users.user_id` | 1:1 с покупателем |
| `email_enc` | BYTEA NOT NULL | application-level encryption |
| `phone_enc` | BYTEA | application-level encryption |
| `key_ref` | TEXT NOT NULL | ссылка на KMS/секрет, ключ не хранится в коде |

**Связи**: 1:1 с `User`.
**Валидация**: PII не покидает vault; в выгрузках только маскированные значения вида `***@domain` (FR-028, SC-009).
**Жизненный цикл**: запись автоматически удаляется по истечении фиксированного срока (по умолчанию 12 месяцев); ручное удаление по запросу отсутствует (FR-037, SC-013).

## API-ключ (ApiKey)

Машинный доступ к данным для выгрузки и подписки (FR-002, FR-036).

| Поле | Тип | Правила |
| --- | --- | --- |
| `key_id` | TEXT PK | `ak_...` |
| `user_id` | TEXT NOT NULL FK → `users.user_id` | владелец |
| `key_prefix` | TEXT NOT NULL | отображаемый префикс |
| `key_hash` | TEXT NOT NULL | argon2/bcrypt, открытый ключ не хранится |
| `scopes` | TEXT[] NOT NULL | по умолчанию `{read}` |
| `created_at` | TIMESTAMPTZ NOT NULL | default `now()` |
| `revoked_at` | TIMESTAMPTZ | NULL, пока ключ активен |

**Связи**: N:1 с `User`.
**Валидация**: ключ аутентифицируется по хешу; отозванный ключ (`revoked_at IS NOT NULL`) отклоняется.
**Переходы**: `ACTIVE → REVOKED` (отзыв, необратимо).

## Провайдер (Provider)

Поставщик данных; владеет метаданными и устройствами/станциями.

| Поле | Тип | Правила |
| --- | --- | --- |
| `provider_id` | TEXT PK | `pv_...` |
| `name` | TEXT NOT NULL | наименование |
| `status` | TEXT NOT NULL | по умолчанию `ACTIVE` |
| `meta_ref` | TEXT | `_id` документа в Mongo `catalog_nosql.provider_meta` |

**Связи**: 1:N с `Dataset`; 1:1 (логически) с документом `provider_meta` в MongoDB (гибкая схема: контакты, `schemas`, `devices`, `tags`, `extra`).
**Валидация**: контакты в Mongo хранятся только маскированными (`valueMasked`).

## Датасет (Dataset)

Продаваемый набор данных с категорией, ценой, лицензией, частотой, схемой полей и рейтингом качества.

| Поле | Тип | Правила |
| --- | --- | --- |
| `dataset_id` | TEXT PK | `ds_...` |
| `provider_id` | TEXT NOT NULL FK → `providers.provider_id` | владелец |
| `name` | TEXT NOT NULL | название |
| `category` | TEXT NOT NULL | `WEATHER` \| `AIR_QUALITY` \| `ENERGY` \| `TRANSPORT` \| `COMMERCE` |
| `frequency_sec` | INT | период обновления потока, сек |
| `volume_estimate` | TEXT | человекочитаемый объём, напр. `1.2M rows/month` |
| `price_per_unit` | NUMERIC(12,2) NOT NULL | неотрицательна, default 0 |
| `quality_score` | NUMERIC(4,3) NOT NULL | `[0..1]`, производное от `quality-service`, вручную не редактируется; запись — только через внутренний `POST /datasets/quality-scores` каталога |
| `licence` | TEXT NOT NULL | напр. `sputnik_edu_v1` |
| `last_updated_at` | TIMESTAMPTZ NOT NULL | момент последнего обновления |

**Связи**: N:1 с `Provider`; 1:N с `DatasetField`; участвует как `productRef` в бизнес-событиях, фигурирует в заказах/подписках/скачиваниях/отзывах и в mart-витринах.
**Валидация**: `quality_score ∈ [0,1]`; `category` из перечисления; `frequency_sec > 0` при наличии.
**Инварианты**: `quality_score` согласован с Quality-page и отчётом качества (FR-020, FR-021).
**Примечание (контракт)**: перечисление категорий ограничено словарём контракта; датасеты о шуме предлагаются под существующей категорией `AIR_QUALITY`, отдельной категории `NOISE` в контракте нет.

## Поле схемы (DatasetField)

Описание столбца датасета для `/schema`.

| Поле | Тип | Правила |
| --- | --- | --- |
| `dataset_id` | TEXT NOT NULL FK → `datasets.dataset_id` | составной PK |
| `ordinal` | INT NOT NULL | порядок поля |
| `name` | TEXT NOT NULL | составной PK |
| `type` | TEXT NOT NULL | `STRING` \| `INT` \| `DOUBLE` \| `BOOLEAN` \| `DATETIME` \| `GEO` |
| `unit` | TEXT | единица измерения, если применимо |
| `nullable` | BOOLEAN NOT NULL | default `true` |

**Связи**: N:1 с `Dataset`; PK `(dataset_id, name)`.

## Заказ (Order)

Факт покупки датасета; определяет право на скачивание (FR-006, FR-007).

| Поле | Тип | Правила |
| --- | --- | --- |
| `order_id` | TEXT PK | `od_...` |
| `user_id` | TEXT NOT NULL | покупатель |
| `dataset_id` | TEXT NOT NULL | продукт |
| `amount` | NUMERIC(12,2) NOT NULL | сумма |
| `currency` | TEXT NOT NULL | default `RUB` |
| `status` | TEXT NOT NULL | `ORDER_PENDING` \| `ORDER_PAID` \| `ORDER_FULFILLED` \| `ORDER_CANCELLED` |
| `idempotency_key` | TEXT NOT NULL | ключ идемпотентности запроса |
| `created_at` | TIMESTAMPTZ NOT NULL | default `now()` |

**Связи**: N:1 с `User`, N:1 с `Dataset`; 1:N с `Subscription` не образует (подписка самостоятельна), право доступа в `delivery` проверяется по `status`.
**Валидация**: `UNIQUE (user_id, idempotency_key)` — повторная покупка не создаёт дубль (FR-006, SC-005).
**Переходы**: `ORDER_PENDING → ORDER_PAID`; `ORDER_PENDING → ORDER_CANCELLED`; `ORDER_PAID → ORDER_FULFILLED`. Скачивание разрешено после оплаты — при `ORDER_PAID` и `ORDER_FULFILLED` (FR-007).
**Примечание (контракт)**: состояния отказа и возврата (`FAILED`/`REFUNDED`) не входят в словарь контракта; отмена заказа выражается состоянием `ORDER_CANCELLED`.

## Подписка (Subscription)

Периодическая доставка свежих данных по датасету (FR-009, FR-022, FR-035).

| Поле | Тип | Правила |
| --- | --- | --- |
| `subscription_id` | TEXT PK | `sub_...` |
| `user_id` | TEXT NOT NULL | покупатель |
| `dataset_id` | TEXT NOT NULL | датасет |
| `interval_sec` | INT NOT NULL | настраиваемый интервал доставки, > 0 |
| `status` | TEXT NOT NULL | `SUB_ACTIVE` \| `SUB_PAUSED` \| `SUB_CANCELLED` |
| `started_at` | TIMESTAMPTZ NOT NULL | default `now()` |
| `cancelled_at` | TIMESTAMPTZ | заполняется при `SUB_CANCELLED` |

**Связи**: N:1 с `User`, N:1 с `Dataset`; порождает событие `commerce.subscriptions`, потребляемое DAG `deliver_subscription`.
**Валидация**: `interval_sec > 0`; переходы только по разрешённой схеме.
**Переходы и семантика** (FR-009, уточнение Q2):
- `SUB_ACTIVE → SUB_PAUSED`: останавливает живой поток и выборку новых данных, но сохраняет подписку и доступ к уже купленным данным.
- `SUB_PAUSED → SUB_ACTIVE`: возобновляет доставку без дублей (SC-005).
- `SUB_ACTIVE → SUB_CANCELLED` и `SUB_PAUSED → SUB_CANCELLED`: окончательно завершает подписку; купленные данные остаются доступными; можно оформить новую подписку.
- `SUB_CANCELLED` — терминальное состояние; `cancelled_at` заполняется.

## Скачивание (Download)

Факт выгрузки датасета с форматом и статусом (FR-005, FR-008).

| Поле | Тип | Правила |
| --- | --- | --- |
| `download_id` | TEXT PK | `dl_...` |
| `user_id` | TEXT NOT NULL | покупатель |
| `dataset_id` | TEXT NOT NULL | датасет |
| `format` | TEXT NOT NULL | `CSV` \| `JSON` \| `PARQUET` |
| `bytes` | BIGINT | размер результата |
| `status` | TEXT NOT NULL | `REQUESTED` \| `DONE` \| `FAILED` |
| `requested_at` | TIMESTAMPTZ NOT NULL | default `now()` |

**Связи**: N:1 с `User`, N:1 с `Dataset`; порождает событие `commerce.downloads`; артефакт — `exports/{user_id}/{download_id}.{ext}` в MinIO.
**Валидация**: формат из поддерживаемого набора; доступ только при оплаченном заказе, иначе отказ (FR-007).
**Переходы**: `REQUESTED → DONE`; `REQUESTED → FAILED`.
**Инвариант PII**: выгрузка не содержит PII (только маскирование) (FR-028, SC-009).

## Отзыв (Review)

Оценка качества датасета покупателем; источник текстов для анализа тональности (FR-010).

| Поле | Тип | Правила |
| --- | --- | --- |
| `review_id` | TEXT PK | `rv_...` |
| `user_id` | TEXT NOT NULL | автор |
| `dataset_id` | TEXT NOT NULL | датасет |
| `rating` | SMALLINT NOT NULL | `CHECK (rating BETWEEN 1 AND 5)` |
| `text` | TEXT | проходит PII-фильтр перед записью |
| `sentiment` | NUMERIC(4,3) | заполняет `transform-service` |
| `created_at` | TIMESTAMPTZ NOT NULL | default `now()` |

**Связи**: N:1 с `User`, N:1 с `Dataset`; порождает событие `commerce.reviews`, потребляемое `transform-service` для `mart_sentiment_daily`.
**Валидация**: рейтинг строго 1–5 (FR-010).
**Правило рейтинга**: число отзывов покупателя на датасет не ограничено, но в рейтинг датасета учитывается только **последний** отзыв покупателя по этому датасету (FR-010, уточнение Q4).

## Чтение датчика (SensorReading)

Единичное измерение станции (content-нить) (FR-011, FR-013).

| Поле | Тип | Правила |
| --- | --- | --- |
| `readingId` | string | `rd_...`, уникален, ключ дедупликации |
| `stationId` | string | `st_...`, ключ партиции |
| `providerId` | string | `pv_...` |
| `metric` | string | напр. `TEMPERATURE`, `PM2_5`, `NOISE`, `ENERGY_KWH` |
| `value` | float64 | числовое значение |
| `unit` | string | единица, напр. `C` |
| `geo` | object | `{ lat: float64, lon: float64 }` |
| `measuredAt` | timestamp | время измерения (UTC) |
| `receivedAt` | timestamp | время приёма (UTC) |

**Связи**: N:1 с `Provider` и станцией (`stationId`); попадает в `sensors.readings.v1`, bronze/silver, `fact_readings`, `mv_readings_hourly`.
**Валидация**: обязательные поля присутствуют, `readingId` не дублируется, значения в допустимых границах; иначе — DLQ с причиной (FR-012, FR-016).
**Инвариант**: `receivedAt` проставляет **только** `sensor-gateway`, не источник (ТЗ §7.2).

## Бизнес-событие (BusinessEvent)

Факт активности на портале; общий конверт `{ eventId, userId, productRef, at, payload }` (FR-025).

**Реконсиляция с AsyncAPI**: машинные контракты `contracts/asyncapi-commerce.yaml` моделируют `EventEnvelope` как `{ eventId, userId, at }` и разворачивают поля топика рядом через `allOf`. Поэтому `productRef` и вложенный `payload` — описательные понятия, а не отдельные поля wire-формата: `productRef` соответствует плоскому `datasetId` события, а payload-ключи из таблицы ниже лежат в корне сообщения.

| Поле | Тип | Правила |
| --- | --- | --- |
| `eventId` | string | `ev_...`, уникален; ключ идемпотентности потребителей |
| `userId` | string | `us_...` |
| `productRef` | object | `{ datasetId: "ds_...", kind: "DATASET" }` |
| `at` | timestamp | момент события (UTC) |
| `payload` | object | типо-зависимый (см. топики) |

**Топики и payload**:

| Топик | Ключ партиции | payload-ключи |
| --- | --- | --- |
| `commerce.clicks` | `datasetId` | `datasetId`, `source` |
| `commerce.orders` | `orderId` | `orderId`, `datasetId`, `amount` |
| `commerce.subscriptions` | `subscriptionId` | `subscriptionId`, `datasetId`, `intervalSec` |
| `commerce.downloads` | `downloadId` | `downloadId`, `datasetId`, `format` |
| `commerce.reviews` | `reviewId` | `reviewId`, `datasetId`, `rating`, `text` |

**Валидация**: `eventId` уникален; схема события объявлена в AsyncAPI и версионируется в имени топика; ломающее изменение — только новый топик/версия (конституция, принцип IV).

## Отчёт о качестве (QualityReport)

Результат проверки слоя данных; источник `qualityScore` (FR-017, FR-020, FR-021).

| Поле | Тип | Правила |
| --- | --- | --- |
| `dt` | Date | дата отчёта |
| `dataset_id` | String | датасет |
| `quality_score` | Float64 | `[0..1]` |
| `missing_rate` | Float64 | доля пропусков |
| `dup_rate` | Float64 | доля дублей |
| `outlier_rate` | Float64 | доля выбросов |
| `anomalies_cnt` | UInt64 | число аномалий |

**Связи**: агрегируется `quality-service`, публикуется в `catalog.datasets.quality_score` и на Quality-page; пишется в `mart_quality_daily`.
**Валидация**: детерминирован по `seed`; пустые данные дают корректные нулевые значения и не прерывают прогон (FR-032).
**Сценарий деградации**: контролируемое загрязнение (`sim-dirty`) снижает `quality_score`; после очистки показатель восстанавливается (FR-017, SC-008).

## Генератор (sim)

Источник детерминированных демонстрационных данных с настраиваемым «загрязнением» (FR-029).

| Модуль | Генерирует | Параметры |
| --- | --- | --- |
| `sim.sensors` | чтения датчиков | seed, станции, интервал, период |
| `sim.providers` | провайдеры + партнёрские CSV | seed, число провайдеров, объём |
| `sim.buyers` | покупатели и поведение | seed, число пользователей |
| `sim.dirty` | контролируемое загрязнение слоя | seed, layer, доли пропусков/дублей/выбросов/битых |

**Инвариант**: одинаковый `seed` → идентичный дайджест выдачи (FR-029, SC-003).

## Инварианты модели

- **Идемпотентность**: `Order` уникален по `(user_id, idempotency_key)`; потребители дедуплицируют по `eventId`/`readingId`; запись слоёв — upsert по ключу/дате; повторный прогон DAG не создаёт дублей (FR-015, FR-023, FR-024, SC-005).
- **DLQ**: битые записи не попадают в silver; фиксируются в `sensors.readings.dlq` с причиной (FR-012, FR-016, SC-004).
- **PII**: только в `identity.pii_vault`, изолированно; маскирование во всех выгрузках; автоматическое удаление по сроку (FR-028, FR-037).
- **Silver без гэпов/дублей**: `validation-service` устраняет дубли и пропуски перед записью silver (FR-017, FR-018).
- **Детерминизм**: генераторы и отчёты воспроизводимы по `seed` (FR-029).

## Отображение сущностей на хранилища

| Сущность | Хранилище | Схема/таблица, коллекция, префикс, топик |
| --- | --- | --- |
| Покупатель (User) | PostgreSQL | `identity.users` |
| PII vault | PostgreSQL | `identity.pii_vault` |
| API-ключ | PostgreSQL | `identity.api_keys` |
| Провайдер (Provider) | PostgreSQL + MongoDB | `catalog.providers` + `catalog_nosql.provider_meta` |
| Датасет (Dataset) | PostgreSQL | `catalog.datasets` |
| Поле схемы (DatasetField) | PostgreSQL | `catalog.dataset_fields` |
| Заказ (Order) | PostgreSQL | `orders.orders` |
| Подписка (Subscription) | PostgreSQL | `orders.subscriptions` |
| Скачивание (Download) | PostgreSQL | `orders.downloads` |
| Отзыв (Review) | PostgreSQL | `reviews.reviews` (сентимент пишет `transform`) |
| Чтение датчика (SensorReading) | Kafka → MinIO → ClickHouse | `sensors.readings.v1` → `lake/bronze/{provider}/{dt}` → `lake/silver/{dataset}/{dt}` → `fact_readings`, `mv_readings_hourly` |
| Бизнес-событие (BusinessEvent) | Kafka → ClickHouse | `commerce.*` → `mart_sales_daily`, `mart_sentiment_daily` |
| Отчёт о качестве (QualityReport) | MinIO + ClickHouse | `lake/reports/quality/{dt}/report.json` + `mart_quality_daily` |
| Генератор (sim) | Kafka / MinIO | `sim-sensors/providers/buyers/dirty` → топики и файлы слоёв |

Дополнительно:

- **DLQ** — Kafka `sensors.readings.dlq` и архив `lake/dlq/{topic}/{dt}/part-*.ndjson`.
- **Партнёрские выгрузки** — `lake/partner/{provider}/{dt}.csv`.
- **Образцы** — `samples/{dataset_id}/sample.{csv,json,parquet}`.
- **Выгрузки** — `exports/{user_id}/{download_id}.{ext}` (signed URL, PII замаскирован).
- **Служебные** — PostgreSQL `airflow` (метаданные планировщика, не бизнес-данные).
