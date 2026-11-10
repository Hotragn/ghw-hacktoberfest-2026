-- Timed in-database stream: 5 devices, clock_timestamp() per row, COMMIT per batch.
-- Simulate the Python producer when a direct Postgres connection is not available.
-- This PROCEDURE uses transaction control (COMMIT) which is legal in PostgreSQL
-- procedures but not in functions.
--
-- CALL bw2026_live.stream_feed(45, 2.0) runs ~45 batches at 2-second intervals
-- (~90 seconds). If the Console editor times out, run a shorter call first
-- (e.g. CALL bw2026_live.stream_feed(10, 2.0);) then the full 45.

CREATE OR REPLACE PROCEDURE bw2026_live.stream_feed(batches int, interval_s float)
LANGUAGE plpgsql
AS $$
DECLARE
  i       int;
  d       text;
  devices text[] := ARRAY['device-1', 'device-2', 'device-3', 'device-4', 'device-5'];
BEGIN
  IF batches IS NULL OR batches < 1 THEN
    RAISE EXCEPTION 'batches must be >= 1';
  END IF;
  IF interval_s IS NULL OR interval_s < 0 THEN
    RAISE EXCEPTION 'interval_s must be >= 0';
  END IF;

  FOR i IN 1..batches LOOP
    FOREACH d IN ARRAY devices LOOP
      INSERT INTO bw2026_live.sensor_readings (ts, device_id, temperature, humidity)
      VALUES (
        clock_timestamp(),
        d,
        round((18.0 + 8.0 * random())::numeric, 2),   -- ~18–26 C
        round((35.0 + 30.0 * random())::numeric, 2)   -- ~35–65 %
      );
    END LOOP;
    COMMIT;
    PERFORM pg_sleep(interval_s);
  END LOOP;
END;
$$;

-- ~45 batches × 2 seconds, 5 devices per batch.
CALL bw2026_live.stream_feed(45, 2.0);
