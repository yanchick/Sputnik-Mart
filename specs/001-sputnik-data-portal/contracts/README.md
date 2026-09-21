# Машинные контракты фичи `001-sputnik-data-portal`

Здесь лежат принятые OpenAPI/AsyncAPI-контракты портала «Спутник Данные». Это единственный источник истины для REST и событий: реализация обязана соответствовать спекам, а не наоборот (Конституция, Принцип I «Контракты прежде кода»). Контракты проверяются автоматически — schemathesis для REST и схемы событий в контрактных тестах; обратно несовместимое изменение допускается только через новую версию и план миграции.

| Файл | Тип | Владелец (сервис) | Что описывает |
| --- | --- | --- | --- |
| `openapi-catalog.yaml` | OpenAPI 3.x | `catalog-service` | каталог датасетов, карточка, схема полей, образец (`/datasets`, `/datasets/{id}`, `/schema`, `/sample`), внутренний пересчёт `qualityScore` (`POST /datasets/quality-scores`) |
| `openapi-order.yaml` | OpenAPI 3.x | `order-service` | создание заказа и подписки, список заказов и подписок, оплата/исполнение (`/orders`, `/orders/{id}/pay`, `/orders/fulfill`, `/orders/access`, `/subscriptions`) |
| `openapi-delivery.yaml` | OpenAPI 3.x | `delivery-service` | выгрузка датасета и живой SSE-поток (`/datasets/{id}/download`, `/streams/{subscriptionId}`) |
| `openapi-identity.yaml` | OpenAPI 3.x | `identity-service` | вход, профиль, подписки покупателя и машинные ключи (`/auth/login`, `/users/me`, `/users/{id}/subscriptions`, `/users/{id}/api-keys`) |
| `openapi-review.yaml` | OpenAPI 3.x | `review-service` | отзывы 1–5 и агрегированный рейтинг (`/reviews`, `/datasets/{id}/rating`) |
| `openapi-quality.yaml` | OpenAPI 3.x | `quality-service` | срез качества и операторский пересчёт `qualityScore` (`/quality`, `/quality/{id}`, `POST /quality/recalculate`) |
| `asyncapi-commerce.yaml` | AsyncAPI 3.0.0 | `catalog-service`, `order-service`, `review-service`, `delivery-service` | бизнес-события `commerce.clicks/orders/subscriptions/downloads/reviews` |
| `asyncapi-content.yaml` | AsyncAPI 3.0.0 | `sensor-gateway`, `ingestion-service` | чтения датчиков `sensors.readings.v1` и очередь ошибок `sensors.readings.dlq` |

## Соглашения

- REST: версия `/api/v1`, camelCase, UTC ISO-8601, единый конверт ошибок с `requestId`, пагинация `{ data, pagination }`, auth Bearer / `X-Api-Key`, заголовки `X-RateLimit-*`. Источник правил — `Docs/spec-kit/contracts/api-conventions.md`.
- События: единый конверт `{ eventId, userId, productRef, at, payload }`; модель доставки at-least-once, идемпотентность по `eventId`/`readingId`; ключи партиций `stationId`/`datasetId`; версия схемы в имени топика. Источник правил — `Docs/spec-kit/contracts/event-conventions.md`. В машинных AsyncAPI-контрактах конверт разворачивается в плоские поля топика (см. «Отклонения», пункт про `EventEnvelope`).
- Данные: общие схемы продукта, заказа и чтения — `Docs/spec-kit/contracts/data-contracts.md`, детальная модель — [../data-model.md](../data-model.md). Upstream-файл `Docs/spec-kit/contracts/data-contracts.md` отстаёт от авторитетного словаря перечислений: авторитетные значения — `SUB_ACTIVE | SUB_PAUSED | SUB_CANCELLED` и `PM2_5` (в upstream остались `"status": "ACTIVE"` и `PM2.5`).

## Изменение контракта

1. Изменить спеку в `specs/001-sputnik-data-portal/contracts/` — эти рабочие копии являются авторитетным редактируемым источником истины (Конституция, Принцип I). Оригиналы в `Docs/specs/` — справочные копии, которые могут отставать (см. раздел «Отклонения» ниже).
2. Обновить реализацию и контрактные тесты в том же PR.
3. Ломающее изменение — только через новую версию (`sensors.readings.v2`) или новый топик, с планом миграции.
4. CI-линтеры OpenAPI/AsyncAPI и контрактные тесты блокируют выпуск при несоответствии.

## Отклонения от Docs/specs originals

Рабочие копии в этом каталоге — **источник истины** (Конституция, Принцип I). Они осознанно отличаются от оригиналов в `Docs/specs/`:

- добавлена security-схема `ApiKeyAuth` (`apiKey`, заголовок `X-Api-Key`); машинные операции доставки принимают либо `bearerAuth`, либо `ApiKeyAuth`;
- добавлены ответы `429` с заголовком `Retry-After` и кодом `RATE_LIMITED` (переиспользуемый компонент `RateLimited`);
- пагинация приведена к `{ total, totalPages, hasMore }` (ранее `{ totalItems, totalPages }`);
- исправлена атрибуция DLQ-топика: его публикуют `sensor-gateway` (записи, отклонённые на приёме), `ingestion-service` (дубли/ядовитые) и `validation-service`;
- добавлены внутренние межсервисные эндпоинты во исполнение правила владения данными (M6): `POST /datasets/quality-scores` (catalog), `POST /api-keys/resolve` (identity), `GET /orders/access`, `POST /orders/fulfill`, `GET /subscriptions`, `GET /subscriptions/{subscriptionId}` (order); они вызываются service-to-service и не заменяют публичные маршруты;
- `Docs/spec-kit/contracts/data-contracts.md` также отстаёт от авторитетного словаря перечислений: рабочие контракты используют `SUB_ACTIVE | SUB_PAUSED | SUB_CANCELLED` (в upstream — `ACTIVE`) и `PM2_5` (в upstream — `PM2.5`); источник истины — `data-model.md` и `specs/001-sputnik-data-portal/contracts/*.yaml`;
- конверт commerce-событий: `asyncapi-commerce.yaml` моделирует `EventEnvelope` как `{ eventId, userId, at }` и разворачивает поля топика рядом через `allOf`; `productRef` и вложенный `payload` из описательного конверта не являются отдельными wire-полями (для конкретного топика `productRef` соответствует плоскому `datasetId`).

Причина: выполнение требований FR-034, FR-036, FR-038 в режиме contract-first.
