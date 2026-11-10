-- Live view for the console after (or during) the stream_feed run.
-- Shows wall-clock now(), the latest 10-second CAGG buckets, rows-per-10s
-- ingestion rate over the last 2 minutes, and the total row count.

SELECT now() AS captured_at, clock_timestamp() AS clock_ts;

-- Latest continuous-aggregate buckets (real-time, materialized_only = false).
SELECT
  bucket,
  device_id,
  samples,
  round(avg_temperature::numeric, 2) AS avg_temperature,
  round(max_temperature::numeric, 2) AS max_temperature,
  round(avg_humidity::numeric, 2)    AS avg_humidity,
  round(max_humidity::numeric, 2)    AS max_humidity
FROM bw2026_live.readings_10s
WHERE bucket > now() - INTERVAL '2 minutes'
ORDER BY bucket DESC, device_id;

-- Ingestion rate: rows per 10-second bucket over the last 2 minutes.
SELECT
  time_bucket(INTERVAL '10 seconds', ts) AS bucket,
  count(*)                               AS rows_in_bucket,
  round((count(*) / 10.0)::numeric, 2)   AS rows_per_second,
  count(DISTINCT device_id)              AS devices
FROM bw2026_live.sensor_readings
WHERE ts > now() - INTERVAL '2 minutes'
GROUP BY 1
ORDER BY 1 DESC;

-- Total count in the fresh schema.
SELECT
  now()                                               AS captured_at,
  count(*)                                            AS total_readings,
  count(DISTINCT device_id)                           AS devices,
  min(ts)                                             AS first_ts,
  max(ts)                                             AS last_ts
FROM bw2026_live.sensor_readings;
