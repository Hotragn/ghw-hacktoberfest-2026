-- Challenge 1: start as an ordinary PostgreSQL table (pre-hypertable).
SET search_path TO builders_week, public;

CREATE TABLE IF NOT EXISTS device_events (
  recorded_at   TIMESTAMPTZ NOT NULL,
  fixture_key   TEXT,
  device_id     TEXT NOT NULL,
  site          TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  severity      SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
  value_celsius DOUBLE PRECISION,
  message       TEXT NOT NULL,
  -- NULL = non-fixture row. Demo SQL sets fixture_batch explicitly; no DEFAULT tags unrelated rows.
  fixture_batch TEXT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS device_events_recorded_fixture_uidx
  ON device_events (recorded_at, fixture_key)
  WHERE fixture_key IS NOT NULL;

COMMENT ON TABLE device_events IS
  'Builders Week sample IoT-style events. Convert to hypertable in 03_convert_hypertable.sql after load.';
