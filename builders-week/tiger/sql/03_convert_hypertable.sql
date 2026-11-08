-- Challenge 1: convert plain table → hypertable after import (nonempty table requires migrate_data).
SET search_path TO builders_week, public;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM timescaledb_information.hypertables
    WHERE hypertable_schema = 'builders_week'
      AND hypertable_name = 'device_events'
  ) THEN
    RAISE NOTICE 'device_events is already a hypertable; skipping create_hypertable';
  ELSE
    PERFORM create_hypertable(
      'builders_week.device_events',
      by_range('recorded_at', INTERVAL '1 day'),
      if_not_exists => TRUE,
      migrate_data => TRUE
    );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS device_events_site_ts
  ON device_events (site, recorded_at DESC);
CREATE INDEX IF NOT EXISTS device_events_device_ts
  ON device_events (device_id, recorded_at DESC);
