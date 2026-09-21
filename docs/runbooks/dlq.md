# Runbook: DLQ и восстановление битых записей

Назначение: эксплуатация очереди ошибок конвейера — причины отбраковки,
расположение архива, разбор и повторная обработка (FR-012, FR-016, SC-004).

## Что попадает в DLQ

Запись уходит в DLQ, если её нельзя безопасно провести в следующий слой.
Причина фиксируется в поле `reason`:

| `reason` | Значение |
| --- | --- |
| `NULL_VALUE` | отсутствует обязательное значение (`value == null`) |
| `OUT_OF_RANGE` | значение вне допустимых границ метрики |
| `SCHEMA_MISMATCH` | не совпадает структура/типы чтения |
| `DUPLICATE` | повтор `readingId` после дедупликации |

В `sensors.readings.dlq` пишут три источника: `sensor-gateway` — записи,
отклонённые уже на приёме (битый конверт/границы), `ingestion` — дубли и
«ядовитые» сообщения, `validation` — повторно отбракованные записи.
`sensor-gateway` фиксирует причину сразу, `ingestion` дополнительно архивирует
битое чтение в `lake/dlq/{topic}/{dt}/part-*.ndjson`.

## Архив

- Топик Kafka: `sensors.readings.dlq` (ключ — `readingId`).
- Озеро: `s3://lake/dlq/sensors.readings.dlq/{dt}/part-*.ndjson`.
- Каждая строка — `DeadReading` с `reason`, `readingId`, `stationId`,
  `receivedAt` и исходным payload.

## Разбор

```bash
# Последние архивы DLQ в MinIO
docker compose exec minio mc ls --recursive local/lake/dlq/ | tail

# Прочитать конкретную партицию
docker compose exec minio mc cat local/lake/dlq/sensors.readings.dlq/<dt>/part-00000.ndjson
```

Сгруппировать по причинам (jq):

```bash
docker compose exec minio mc cat local/lake/dlq/sensors.readings.dlq/<dt>/part-00000.ndjson \
  | jq -r '.reason' | sort | uniq -c
```

## Восстановление

1. **`SCHEMA_MISMATCH` / `NULL_VALUE`.** Исправить источник или генератор;
   перегенерировать записи с тем же `seed` и переотправить в
   `POST /api/v1/readings`. Дедупликация по `readingId` не создаст дублей.
2. **`OUT_OF_RANGE`.** Подтвердить границы метрики; если выброс
   контролируемый (учебный), очистить источник и прогнать слой заново.
3. **`DUPLICATE`.** Штатное поведение at-least-once: повтор игнорируется.
   Проверить, что в silver нет дублей (SC-005); при необходимости перезапустить
   `ingest_readings` — идемпотентный upsert не создаст новых записей.
4. После исправления повторить прогон слоёв (см. `docs/runbooks/pipeline.md`) и
   убедиться, что доля `dead` стремится к нулю.

## Диагностика

- **100% записей в DLQ.** Проверить формат конверта и метрику; вероятно,
  `SCHEMA_MISMATCH` или общий `NULL_VALUE`.
- **DLQ растёт при валидных данных.** Проверить версию схемы события в
  `libs/contracts/src/contracts/events_content.py` и совместимость с
  `sensor-gateway`.
- **Архив DLQ пуст, а Kafka-топик не пуст.** Проверить права/доступность MinIO и
  логи `CompositeDlq` в `ingestion`.
- **Записи «ядовитые» и валят консьюмер.** `ingestion` ловит ошибку валидации и
  шлёт в DLQ; после исчерпания ретраев сообщение не блокирует консьюмер.

## Гарантия

`at-least-once` + идемпотентные консьюмеры (дедупликация по `readingId` в
Redis). Повторная обработка DLQ-записи не создаёт дублей в silver/gold.
100% невалидных записей — в DLQ, 0% — в silver (SC-004).

## Проверка тестами

```bash
uv run pytest -q tests/integration/test_us2_dlq.py tests/unit/services/test_ingestion.py
```
