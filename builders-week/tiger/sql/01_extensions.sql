-- Enable TimescaleDB + pgvector + pgvectorscale when present. Fail loudly on real errors.
SET search_path TO builders_week, public;

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    RAISE NOTICE 'vectorscale already installed';
  ELSIF EXISTS (
    SELECT 1 FROM pg_available_extensions WHERE name = 'vectorscale' AND default_version IS NOT NULL
  ) THEN
    CREATE EXTENSION vectorscale CASCADE;
    RAISE NOTICE 'vectorscale installed from pg_available_extensions';
  ELSE
    RAISE WARNING 'vectorscale is NOT listed in pg_available_extensions on this instance; pgvector HNSW fallback only — Challenge 5 pgvectorscale requirement not met until Tiger Cloud proves otherwise';
  END IF;
END $$;
