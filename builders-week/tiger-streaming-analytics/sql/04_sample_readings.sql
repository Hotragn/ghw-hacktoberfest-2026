-- Optional static seed (no DELETE). Live feed comes from producer/iot_producer.py
SET search_path TO bw2026_stream, public;

INSERT INTO iot_readings
  (recorded_at, fixture_key, device_id, site, celsius, battery_pct, fixture_batch)
VALUES
  (now() - INTERVAL '3 minutes', 'seed-sensor-1|t0', 'sensor-1', 'lab-east', 21.5, 98, 'bw2026-stream-seed'),
  (now() - INTERVAL '2 minutes', 'seed-sensor-2|t0', 'sensor-2', 'lab-east', 22.1, 95, 'bw2026-stream-seed'),
  (now() - INTERVAL '1 minute', 'seed-sensor-1|t1', 'sensor-1', 'lab-east', 21.8, 97, 'bw2026-stream-seed')
ON CONFLICT (recorded_at, fixture_key) WHERE fixture_key IS NOT NULL
DO NOTHING;
