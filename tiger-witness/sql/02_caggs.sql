SET search_path TO witness, public;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS spend_daily WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS bucket, user_id, merchant, category,
       sum(amount) AS total, count(*) AS n
FROM witness.life_events WHERE kind IN ('txn','bill','subscription') AND amount IS NOT NULL
GROUP BY 1,2,3,4 WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS spend_monthly WITH (timescaledb.continuous) AS
SELECT time_bucket('30 days', bucket) AS bucket, user_id, merchant, category,
       sum(total) AS total, sum(n) AS n
FROM witness.spend_daily GROUP BY 1,2,3,4 WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS actions_hourly WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS bucket, user_id, mandate_id, decision,
       count(*) AS n, sum(coalesce(amount,0)) AS amount
FROM witness.actions GROUP BY 1,2,3,4 WITH NO DATA;
-- @@
SELECT add_continuous_aggregate_policy('witness.spend_daily',   start_offset => INTERVAL '400 days', end_offset => NULL, schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
-- @@
SELECT add_continuous_aggregate_policy('witness.spend_monthly', start_offset => INTERVAL '400 days', end_offset => NULL, schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
-- @@
SELECT add_continuous_aggregate_policy('witness.actions_hourly', start_offset => INTERVAL '30 days', end_offset => NULL, schedule_interval => INTERVAL '5 minutes', if_not_exists => TRUE);
