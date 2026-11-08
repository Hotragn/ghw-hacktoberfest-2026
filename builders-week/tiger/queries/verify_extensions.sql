-- Verify required extensions (read-only).
SET search_path TO builders_week, public;

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('timescaledb', 'vector', 'vectorscale')
ORDER BY extname;
