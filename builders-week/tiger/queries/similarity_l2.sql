-- Challenge 5: Euclidean / L2 distance (<-> operator).
SET search_path TO builders_week, public;

WITH q AS (
  SELECT '[0.589861,-0.175082,-0.057319,-0.294931,-0.063572,0.097963,-0.053150,-0.056277,0.198010,0.401231,-0.218853,-0.357460,-0.030223,0.174040,0.279298,-0.162577]'::vector AS query_vec
)
SELECT
  a.recorded_at,
  a.site,
  a.summary_text,
  (a.embedding <-> q.query_vec) AS l2_distance
FROM alert_embeddings a, q
ORDER BY a.embedding <-> q.query_vec
LIMIT 5;
