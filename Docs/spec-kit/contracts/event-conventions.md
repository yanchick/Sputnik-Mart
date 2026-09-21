---
tags:
  - ДДЕ
  - события
  - конвенции
  - спецификация
status: принят
---

# Конвенции событий (AsyncAPI)

Соглашения для event-контрактов. Машинные спеки — `specs/asyncapi-commerce.yaml`
и `specs/asyncapi-content.yaml`.

## Общий конверт события (commerce)

Каждое commerce-событие оборачивается единым конвертом:

```jsonc
{
  "eventId": "ev_...",
  "userId": "us_...",
  "productRef": { "datasetId": "ds_weather-stations", "kind": "DATASET" },
  "at": "2026-09-07T12:34:56Z",
  "payload": { /* типозависимо */ }
}
```

- `eventId` — уникален, используется для идемпотентности потребителей.
- `at` — момент события (UTC ISO-8601).
- `payload` — специфичен для топика.

## Топики commerce (`specs/asyncapi-commerce.yaml`)

| Топик | Смысл | payload-ключи |
| --- | --- | --- |
| `commerce.clicks` | Просмотр карточки/образца | `datasetId`, `source` |
| `commerce.orders` | Покупка датасета | `orderId`, `datasetId`, `amount` |
| `commerce.subscriptions` | Подписка на поток | `subscriptionId`, `datasetId`, `intervalSec` |
| `commerce.downloads` | Выгрузка | `downloadId`, `datasetId`, `format` |
| `commerce.reviews` | Отзыв о качестве | `reviewId`, `datasetId`, `rating`, `text` |

## Content: чтения датчиков (`specs/asyncapi-content.yaml`)

Топик `sensors.readings.v1` (схема в §4.2 ТЗ):

```jsonc
{
  "readingId": "rd_9f2c",
  "stationId": "st_metro-01",
  "providerId": "pv_metro",
  "metric": "TEMPERATURE",
  "value": 18.4,
  "unit": "C",
  "geo": { "lat": 59.93, "lon": 30.31 },
  "measuredAt": "2026-09-07T12:34:56Z",
  "receivedAt": "2026-09-07T12:34:56Z"
}
```

DLQ-топик: `sensors.readings.dlq` — битые записи, не прошедшие схему/валидацию.

## Гарантии доставки и ключи партиций

- **At-least-once** + идемпотентные потребители по `eventId`/`readingId`
  (повторные прогоны DAGов не создают дублей — см. §8 ТЗ и [[../milestones]]).
- Ключ партиции: `productRef.datasetId` (commerce) / `stationId` (readings) —
  сохраняет порядок по одному продукту/станции.
- `receivedAt` ставится на приёме в `sensor-gateway`, не на источнике.

## Схемы и версионирование

- Схемы живут в AsyncAPI-спеках; название схемы = версия топика (`v1`).
- Ломающее изменение → новый топик/версия (например `sensors.readings.v2`),
  старый продолжает работать до миграции потребителей.
- Валидация записей в CI + на входе `ingestion-service` (см. §9 ТЗ).

## Ссылки

- Схемы-примеры — [[../../ТЗ — Демо-портал маркетплейса данных (SDD)]] §4.
- Слои и хранение событий — [[Контракты данных, генераторы и слои]] §слои.
