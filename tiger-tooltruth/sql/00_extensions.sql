-- One Tiger service hosts both projects; each lives in its own schema.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
-- pgvectorscale (StreamingDiskANN) is available on Tiger Cloud; optional locally.
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'vectorscale not available here (%), falling back to pgvector HNSW', SQLERRM;
END $$;
CREATE SCHEMA IF NOT EXISTS tooltruth;
