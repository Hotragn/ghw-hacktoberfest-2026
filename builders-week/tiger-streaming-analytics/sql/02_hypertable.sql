-- Mock IoT ping readings (fixture rows use explicit fixture_key + INSERT ON CONFLICT).
SET search_path TO bw2026_stream, public;

CREATE TABLE IF NOT EXISTS iot_readings (
  recorded_at     TIMESTAMPTZ NOT NULL,
  fixture_key     TEXT,
  device_id       TEXT NOT NULL,
  site            TEXT NOT NULL DEFAULT 'demo-site',
  celsius         DOUBLE PRECISION NOT NULL,
  battery_pct     SMALLINT CHECK (battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100),
  fixture_batch   TEXT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS iot_readings_recorded_fixture_uidx
  ON iot_readings (recorded_at, fixture_key)
  WHERE fixture_key IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM timescaledb_information.hypertables
    WHERE hypertable_schema = 'bw2026_stream' AND hypertable_name = 'iot_readings'
  ) THEN
    PERFORM create_hypertable(
      'bw2026_stream.iot_readings',
      by_range('recorded_at', INTERVAL '1 day'),
      if_not_exists => TRUE
    );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS iot_readings_device_ts
  ON iot_readings (device_id, recorded_at DESC);
