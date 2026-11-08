-- Enable TimescaleDB + pgvector (+ pgvectorscale on Tiger Cloud). Idempotent.
SET search_path TO builders_week, public;

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

-- pgvectorscale provides StreamingDiskANN; optional on self-hosted Postgres.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    BEGIN
      CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
    EXCEPTION
      WHEN OTHERS THEN
        RAISE NOTICE 'vectorscale not available on this instance (%); pgvector HNSW fallback will be used', SQLERRM;
    END;
  END IF;
END $$;
