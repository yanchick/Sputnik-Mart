-- Спутник Данные — ClickHouse gold: факты чтений и часовой MV (T048).
-- Engine MergeTree, партиционирование по месяцу, порядок по станции/метрике/времени.

CREATE DATABASE IF NOT EXISTS sputnik;

CREATE TABLE IF NOT EXISTS sputnik.fact_readings
(
    reading_id   String,
    station_id   String,
    provider_id  String,
    metric       LowCardinality(String),
    value        Float64,
    unit         String,
    lat          Float64,
    lon          Float64,
    measured_at  DateTime64(3, 'UTC'),
    received_at  DateTime64(3, 'UTC'),
    dt           Date DEFAULT toDate(measured_at)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(dt)
ORDER BY (station_id, metric, measured_at);

-- Целевая таблица часовых агрегатов, наполняется Materialized View.
CREATE TABLE IF NOT EXISTS sputnik.mv_readings_hourly
(
    station_id String,
    metric     LowCardinality(String),
    hour       DateTime,
    readings   UInt64,
    avg_value  Float64,
    min_value  Float64,
    max_value  Float64
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (station_id, metric, hour);

CREATE MATERIALIZED VIEW IF NOT EXISTS sputnik.mv_readings_hourly_agg
TO sputnik.mv_readings_hourly
AS
SELECT
    station_id,
    metric,
    toStartOfHour(measured_at) AS hour,
    count()                    AS readings,
    avg(value)                 AS avg_value,
    min(value)                 AS min_value,
    max(value)                 AS max_value
FROM sputnik.fact_readings
GROUP BY station_id, metric, hour;
