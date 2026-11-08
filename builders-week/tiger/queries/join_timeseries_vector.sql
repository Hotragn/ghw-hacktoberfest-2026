-- Hybrid: time-series device events + nearest alert embedding for same device (same day).
SET search_path TO builders_week, public;

SELECT
  d.recorded_at,
  d.device_id,
  d.event_type,
  d.message AS event_message,
  a.summary_text AS nearest_alert,
  (a.embedding <=> (
    SELECT embedding FROM alert_embeddings
    WHERE device_id = d.device_id
    ORDER BY recorded_at DESC LIMIT 1
  )) AS distance_to_latest_device_alert
FROM device_events d
LEFT JOIN LATERAL (
  SELECT *
  FROM alert_embeddings ae
  WHERE ae.device_id = d.device_id
    AND ae.recorded_at >= d.recorded_at - INTERVAL '6 hours'
    AND ae.recorded_at <= d.recorded_at + INTERVAL '6 hours'
  ORDER BY ae.recorded_at
  LIMIT 1
) a ON TRUE
WHERE d.severity >= 3
ORDER BY d.recorded_at
LIMIT 15;
