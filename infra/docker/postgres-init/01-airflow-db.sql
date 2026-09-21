-- Спутник Данные — создание служебной БД Airflow при первой инициализации Postgres.
-- Выполняется docker-entrypoint-initdb.d при пустом томе pgdata.
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
