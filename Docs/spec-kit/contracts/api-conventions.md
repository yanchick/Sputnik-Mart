---
tags:
  - ДДЕ
  - API
  - конвенции
  - спецификация
status: принят
---

# Конвенции REST API (gateway)

Общие правила для всех REST-эндпоинтов. Машинные контракты — `specs/openapi-*.yaml`;
здесь — соглашения, которые эти спеки реализуют.

## Базовые соглашения

- Версия в пути: `/api/v1`.
- Обмен: `application/json`.
- Имена полей: **camelCase**.
- Идентификаторы: `{prefix}_{...}` (например `ds_weather-stations`, `us_...`, `sub_7a1b`).
- Временные метки: **UTC ISO-8601** (`2026-09-07T12:34:56Z`).
- Числа с плавающей точкой: float64.

## Аутентификация

- Bearer-токен (`Authorization: Bearer <token>`) для покупателей.
- API-ключ (`X-Api-Key`) для машинного доступа к данным (download/stream).
- Токены/ключи выдаёт `identity-service`.

## Стандартный формат ошибок

Все ошибки — единая обёртка:

```jsonc
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Датасет не найден",
    "requestId": "req_9f2c...",
    "details": { }
  }
}
```

- `code` — машинный (см. ниже), `message` — человекочитаемый.
- `requestId` обязателен в каждом ответе об ошибке (трассировка через gateway).

| HTTP | `code` | Типичный случай |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | Некорректные query/body |
| 401 | `UNAUTHORIZED` | Нет/битый токен |
| 403 | `FORBIDDEN` | Нет прав (не куплен датасет) |
| 404 | `RESOURCE_NOT_FOUND` | Ресурс не найден |
| 409 | `CONFLICT` | Конфликт состояния (дубль заказа) |
| 422 | `VALIDATION_ERROR` | Схема/поля не прошли валидацию |
| 429 | `RATE_LIMITED` | Превышен лимит |
| 500 | `INTERNAL_ERROR` | Внутренняя ошибка |
| 503 | `UNAVAILABLE` | Сервис недоступен / деградация |

## Пагинация

Списочные эндпоинты возвращают обёртку `{ data, pagination }`:

```jsonc
{
  "data": [ /* записи */ ],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "total": 137,
    "totalPages": 7,
    "hasMore": true
  }
}
```

Параметры запроса: `page` (1-based), `pageSize` (по умолчанию 20, макс 100).

## Rate-limit

Gateway добавляет заголовки (политика лимита в gateway):

- `X-RateLimit-Limit` — сколько запросов разрешено за окно.
- `X-RateLimit-Remaining` — осталось.
- `X-RateLimit-Reset` — когда окно сбросится (epoch).
- При превышении — `429 RATE_LIMITED` с `Retry-After`.

## requestId и трассировка

- Gateway генерирует `requestId` на входе, прокидывает его downstream-сервисам
  (заголовок `X-Request-Id`), возвращает в ответах и ошибках.
- Используется при связывании логов сервисов в observability.

## Живой поток

`GET /api/v1/streams/{subscriptionId}` — **SSE** (`text/event-stream`),
см. [[../adr/ADR-0003 — Живой поток SSE]]. События идут как `event: reading` с полем `id`
= `readingId` (идемпотентность на клиенте) и `event: ping` для keep-alive.

## Ссылки

- Спеки сервисов: `specs/openapi-*.yaml` ([[../README]] проекта).
- Авторизация/правки — см. [[../../ТЗ — Демо-портал маркетплейса данных (SDD)]] §5.
