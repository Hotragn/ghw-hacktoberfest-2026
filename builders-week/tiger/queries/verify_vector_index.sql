-- Report which vector index type exists (read-only).
SET search_path TO builders_week, public;

SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'builders_week'
  AND tablename = 'alert_embeddings'
  AND indexname LIKE 'alert_embeddings_%';

SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') AS vectorscale_installed;
