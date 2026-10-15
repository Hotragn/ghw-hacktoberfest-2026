SET search_path TO scamshield, public;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS signals_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', ts) AS bucket, household_id, kind,
       count(*) AS events,
       sum(value) AS total_value,
       max(value) AS max_value,
       count(*) FILTER (WHERE local_hour >= 22 OR local_hour < 6) AS night_events,
       sum(value) FILTER (WHERE kind = 'call' AND (local_hour >= 22 OR local_hour < 6)) AS night_call_minutes,
       count(*) FILTER (WHERE (meta->>'intl')::boolean) AS intl_events,
       count(*) FILTER (WHERE meta->>'place' = 'crypto_kiosk') AS kiosk_visits
FROM home_signals GROUP BY bucket, household_id, kind
WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS tx_daily
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 day', ts) AS bucket, household_id, kind,
       count(*) AS n, sum(amount_usd) AS usd, sum(btc_amount) AS btc, avg(btc_usd) AS avg_btc_usd
FROM transactions GROUP BY bucket, household_id, kind
WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS btc_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 minute', ts) AS bucket, product,
       first(price, ts) AS open, max(price) AS high, min(price) AS low, last(price, ts) AS close, count(*) AS ticks
FROM btc_ticks GROUP BY bucket, product
WITH NO DATA;
