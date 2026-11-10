-- Tiger Challenge 4 / Builders Week — fresh live-stream schema
-- Run in the Tiger Console SQL editor against service ghw-tiger (vum48trstx).
-- Everything lives in schema bw2026_live. No DROP / DELETE / TRUNCATE outside it.
-- Safe to re-run: uses IF NOT EXISTS / if_not_exists.

CREATE SCHEMA IF NOT EXISTS bw2026_live;

CREATE TABLE IF NOT EXISTS bw2026_live.sensor_readings (
  ts          TIMESTAMPTZ      NOT NULL,
  device_id   TEXT             NOT NULL,
  temperature DOUBLE PRECISION NOT NULL,
  humidity    DOUBLE PRECISION NOT NULL
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM timescaledb_information.hypertables
    WHERE hypertable_schema = 'bw2026_live'
      AND hypertable_name   = 'sensor_readings'
  ) THEN
    PERFORM create_hypertable(
      'bw2026_live.sensor_readings',
      by_range('ts', INTERVAL '1 day'),
      if_not_exists => TRUE
    );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS sensor_readings_device_ts
  ON bw2026_live.sensor_readings (device_id, ts DESC);

-- Real-time continuous aggregate: 10-second buckets, avg/max/count per device.
-- materialized_only = false so the latest (not-yet-materialized) bucket is
-- filled in from the hypertable at query time.
CREATE MATERIALIZED VIEW IF NOT EXISTS bw2026_live.readings_10s
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
  time_bucket(INTERVAL '10 seconds', ts) AS bucket,
  device_id,
  count(*)               AS samples,
  avg(temperature)       AS avg_temperature,
  max(temperature)       AS max_temperature,
  avg(humidity)          AS avg_humidity,
  max(humidity)          AS max_humidity
FROM bw2026_live.sensor_readings
GROUP BY bucket, device_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
  'bw2026_live.readings_10s',
  start_offset      => INTERVAL '1 hour',
  end_offset        => INTERVAL '10 seconds',
  schedule_interval => INTERVAL '10 seconds',
  if_not_exists     => TRUE
);
