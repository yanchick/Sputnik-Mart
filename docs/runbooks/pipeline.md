# Runbook: конвейер данных (bronze → silver → gold)

Назначение: эксплуатация конвейера US2 — от генератора чтений датчиков до
gold-витрин и пересчёта `qualityScore` (FR-011…FR-024, SC-003…SC-008).
Профиль — `adv` (или `demo`).

## Компоненты и слои

| Слой | Сервис / DAG | Артефакт |
| --- | --- | --- |
| Источник | `sim.sensors` / `sim.dirty` | NDJSON чтений (детерминированный `seed`) |
| Приём | `sensor-gateway` `POST /api/v1/readings` | `sensors.readings.v1` (ключ `stationId`) |
| Бронза | `ingestion` | `lake/bronze/{provider}/{dt}/part-*.ndjson` |
| Очередь ошибок | `sensor-gateway` / `ingestion` / `validation` | `sensors.readings.dlq`, `lake/dlq/{topic}/{dt}/part-*.ndjson` |
| Серебро | `validation` | `lake/silver/{dataset}/{dt}/part-*.parquet` |
| Отчёт качества | `validation` | `lake/reports/quality/{dt}/report.json` |
| Золото | `transform` | ClickHouse `fact_readings`, `mv_readings_hourly`, `mart_*` |
| Рейтинг | `quality` | `qualityScore` в каталоге и Quality-page |

DAGи: `ingest_readings` (`pull_bronze → validate → silver → transform →
load_gold`), `refresh_quality` (retries + backoff + сенсоры свежести),
`sync_provider_exports` (партнёрский CSV → bronze → silver).

## Границы идемпотентности (FR-015)

Дедупликация `ingestion` по `readingId` хранится в Redis с TTL **24 часа**
(`RedisDeduplicator`, `ttl_seconds=86_400`, `services/ingestion/src/ingestion/consumer.py`).
Это означает: повторная доставка того же `readingId` в пределах суток
отбрасывается как `DUPLICATE`; при повторной доставке спустя больше 24 часов
запись может быть обработана повторно (запись в слои при этом идемпотентна
через upsert по детерминированным ключам). Граница зафиксирована осознанно —
для демо-периода этого достаточно, а TTL не позволяет ключам копиться
бесконечно.

## Штатный прогон

```bash
# 1. Сгенерировать чтения с фиксированным seed в файл
uv run sim sensors --seed 42 --periods 24 --out /tmp/readings.ndjson

# 2. Применить контролируемое загрязнение (опционально)
uv run sim dirty --input /tmp/readings.ndjson --seed 42 --missing 0.1 --duplicate 0.05 --out /tmp/dirty.ndjson

# 3. Отправить в шлюз
curl -sS -X POST http://localhost:8006/api/v1/readings \
  -H 'Content-Type: application/json' \
  --data @/tmp/dirty.ndjson

# 4. Прогнать слои вручную (или дождаться Airflow)
uv run python -m ingestion.main
uv run python -m validation.main
uv run python -m transform.main

# 5. Пересчитать рейтинг
curl -sS -X POST http://localhost:8007/api/v1/quality/recalculate \
  -H 'Content-Type: application/json' -d '{"datasets": {}}'
```

## Проверка результата

- **Silver без дублей и пропусков.** `validation` дедуплицирует по
  детерминированным ключам/партициям; повторный прогон не создаёт новых
  объектов (SC-005).
- **100% невалидных в DLQ, 0% в silver** (SC-004) — сверяется по архиву DLQ и
  числу записей silver.
- **Отчёт качества** содержит `missing`, `dup`, `outlier`, `anomaly`.
- **`qualityScore` в каталоге совпадает с отчётом** — формула
  `quality_score_from_rates` едина для validation и quality (FR-020).

## Деградация и восстановление (SC-008)

1. Зафиксировать базовый `qualityScore` датасета (каталог / Quality-page).
2. Прогнать `sim.dirty` с ненулевыми долями загрязнения и завершить слои.
3. Убедиться, что показатель снизился и отображается на Quality-page.
4. Прогнать чистый `sim` и слои — показатель возвращается к базовому.

## Детерминированность (SC-003)

`sim sensors`/`sim dirty` при одинаковом `seed` дают побайтово идентичный
NDJSON. Для сверки:

```bash
uv run sim sensors --seed 42 --periods 6 --out /tmp/a.ndjson
uv run sim sensors --seed 42 --periods 6 --out /tmp/b.ndjson
cmp /tmp/a.ndjson /tmp/b.ndjson && echo deterministic
```

## Диагностика

- **Пустой источник.** Конвейер завершается успешно с нулевыми результатами и
  не падает (FR-032); смотреть `lake/reports/quality/*/report.json`.
- **`receivedAt` не проставлен / проставлен не шлюзом.** Проверить
  `sensor-gateway`: только он добавляет `receivedAt`; `measuredAt` приходит от
  источника (FR-011).
- **Витрина не обновилась.** Проверить `transform_done` в логах и доступность
  ClickHouse; повторить `uv run python -m transform.main` — upsert
  идемпотентен.
- **Рейтинг не меняется.** Проверить, что `quality/recalculate` вызван после
  публикации отчёта, и что `datasetId` в отчёте совпадает с каталогом.
- **Партнёрская выгрузка не появилась.** Проверить DAG
  `sync_provider_exports` и схему CSV; при несоответствии Pandera запись не
  попадает в silver (FR-033).

## Проверка тестами

```bash
uv run pytest -q tests/integration/test_us2_content_pipeline.py tests/integration/test_us2_dlq.py \
  tests/integration/test_us2_quality_degradation.py tests/integration/test_us2_partner_export.py \
  tests/e2e/test_seed_determinism.py
```
