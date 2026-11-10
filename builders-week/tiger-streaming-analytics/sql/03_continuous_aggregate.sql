-- Rolling 1-minute averages for dashboard (Timescale continuous aggregate).
SET search_path TO bw2026_stream, public;

CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
  time_bucket(INTERVAL '1 minute', recorded_at) AS bucket,
  device_id,
  site,
  count(*)                     AS samples,
  avg(celsius)                   AS avg_celsius,
  min(celsius)                   AS min_celsius,
  max(celsius)                   AS max_celsius
FROM iot_readings
GROUP BY bucket, device_id, site
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
  'bw2026_stream.readings_1m',
  start_offset => INTERVAL '2 hours',
  end_offset => INTERVAL '0 minutes',
  schedule_interval => INTERVAL '1 minute',
  if_not_exists => TRUE
);
