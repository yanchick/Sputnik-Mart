-- Спутник Данные — ClickHouse gold: аналитические витрины mart_* (T049).
-- Витрины заполняются transform-service идемпотентно по (dt, dataset_id).

CREATE TABLE IF NOT EXISTS sputnik.mart_sales_daily
(
    dt           Date,
    dataset_id   String,
    orders       UInt64,
    downloads    UInt64,
    clicks       UInt64,
    gross_amount Decimal(18, 2),
    updated_at   DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (dt, dataset_id);

CREATE TABLE IF NOT EXISTS sputnik.mart_quality_daily
(
    dt            Date,
    dataset_id    String,
    quality_score Float64,
    missing_rate  Float64,
    dup_rate      Float64,
    outlier_rate  Float64,
    anomalies_cnt UInt64,
    updated_at    DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (dt, dataset_id);

CREATE TABLE IF NOT EXISTS sputnik.mart_sentiment_daily
(
    dt            Date,
    dataset_id    String,
    reviews       UInt64,
    avg_rating    Float64,
    avg_sentiment Float64,
    positive      UInt64,
    negative      UInt64,
    updated_at    DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (dt, dataset_id);

-- Целевая таблица прогноза часовых рядов (FR-019, SC-006). Наполняется
-- transform-service из gold/staging/{dt}/forecasts.ndjson идемпотентно по
-- ключу (station_id, metric, hour).
CREATE TABLE IF NOT EXISTS sputnik.forecasts
(
    station_id     String,
    metric         LowCardinality(String),
    hour           DateTime,
    forecast_value Float64,
    updated_at     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(hour)
ORDER BY (station_id, metric, hour);
