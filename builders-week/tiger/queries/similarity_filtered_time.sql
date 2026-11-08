-- Similarity + time-range filter (hybrid time-series + vector search).
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '[0.460147,-0.205772,0.049512,-0.098570,0.028617,0.125825,0.139452,-0.057689,0.342953,0.389285,-0.057689,-0.259372,0.181242,-0.023166,0.241202,-0.512839]'::vector AS query_vec
)
SELECT
  a.recorded_at,
  a.device_id,
  a.summary_text,
  (a.embedding <=> q.query_vec) AS cosine_distance
FROM alert_embeddings a, q
WHERE a.recorded_at >= TIMESTAMPTZ '2026-11-02 00:00:00+00'
  AND a.recorded_at <  TIMESTAMPTZ '2026-11-03 00:00:00+00'
ORDER BY a.embedding <=> q.query_vec
LIMIT 5;
