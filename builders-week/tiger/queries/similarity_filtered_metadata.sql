-- Similarity + metadata filters (site, severity, tags).
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '[0.370151,0.096737,-0.286737,-0.102530,-0.313383,0.049238,-0.289054,-0.035335,-0.090945,0.115274,0.238078,-0.158140,-0.180152,-0.114115,0.630820,-0.169725]'::vector AS query_vec
)
SELECT
  a.recorded_at,
  a.site,
  a.severity,
  a.tags,
  a.summary_text,
  (a.embedding <=> q.query_vec) AS cosine_distance
FROM alert_embeddings a, q
WHERE a.site = 'lab-east'
  AND a.severity >= 3
  AND 'thermal' = ANY (a.tags)
  AND (a.embedding <=> q.query_vec) < 0.65
ORDER BY a.embedding <=> q.query_vec
LIMIT 10;
