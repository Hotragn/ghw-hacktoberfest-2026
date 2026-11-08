-- Challenge 1: start as an ordinary PostgreSQL table (pre-hypertable).
SET search_path TO builders_week, public;

CREATE TABLE IF NOT EXISTS device_events (
  recorded_at   TIMESTAMPTZ NOT NULL,
  device_id     TEXT NOT NULL,
  site          TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  severity      SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
  value_celsius DOUBLE PRECISION,
  message       TEXT NOT NULL
);

COMMENT ON TABLE device_events IS
  'Builders Week sample IoT-style events. Convert to hypertable in 03_convert_hypertable.sql after load.';
