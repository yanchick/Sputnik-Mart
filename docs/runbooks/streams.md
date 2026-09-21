# Runbook: живой поток подписок (SSE)

Назначение: эксплуатация сквозного сценария «подписка → свежие чтения → живой
график» (US3, FR-022, FR-023, FR-035, SC-006).

## Компоненты

- `order-service` — создаёт подписку (`SUB_ACTIVE`) и публикует `commerce.subscriptions`.
- DAG `deliver_subscription` — по активным подпискам выбирает свежие чтения из `fact_readings` и дедуплицирует их по `readingId` в Redis.
- `delivery-service` — `GET /api/v1/streams/{subscriptionId}` отдаёт SSE (`event: reading`, `id = readingId`, keep-alive `event: ping`).
- `web-vitrina` — Panel-страница «Живой поток» читает SSE через `httpx-sse`.

## Штатный сценарий

1. Оформить подписку: `POST /api/v1/subscriptions` (Bearer или UI-кабинет).
2. Подключиться: `GET /api/v1/streams/{subscriptionId}` (Bearer **или** `X-Api-Key`).
3. Убедиться, что у кадров `event: reading` поле `id` уникально.
4. Разорвать и восстановить соединение — повторно доставленные кадры не появляются.

## Статусы подписки

| Действие | Переход | Эффект |
| --- | --- | --- |
| `POST /subscriptions/{id}/pause` | `SUB_ACTIVE → SUB_PAUSED` | поток и выборка новых данных останавливаются, подписка и купленные данные сохранены |
| `POST /subscriptions/{id}/resume` | `SUB_PAUSED → SUB_ACTIVE` | доставка продолжается без дублей |
| `POST /subscriptions/{id}/cancel` | `* → SUB_CANCELLED` | подписка завершена, `cancelled_at` заполнен; купленные данные доступны, можно оформить новую |

`SUB_CANCELLED` терминален: повторная пауза/возобновление возвращает `409 CONFLICT`.
Попытка открыть поток неактивной подписки возвращает `403 FORBIDDEN`.

## Диагностика

- **Поток пуст.** Проверить статус подписки, наличие чтений в `fact_readings` по метрикам датасета и корректность `datasetId`.
- **Дубли кадров.** Проверить доступность Redis: при недоступности дедупликация деградирует до памяти процесса.
- **Поток не открывается (401).** Проверить Bearer-токен или активность `X-Api-Key` (`identity.api_keys.revoked_at IS NULL`).
- **Поток не открывается (403).** Подписка приостановлена/отменена либо принадлежит другому покупателю.
- **429 RATE_LIMITED.** SSE и выгрузки лимитируются отдельной областью (`stream`/`export`); ориентироваться на `Retry-After`.

## Проверка

```bash
uv run pytest -q tests/contract/test_stream_sse.py tests/integration/test_us3_subscription_stream.py tests/integration/test_us3_subscription_states.py tests/e2e/test_us3_end_to_end.py
```
