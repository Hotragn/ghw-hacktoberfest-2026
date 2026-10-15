SET search_path TO tooltruth, public;
-- Prefer pgvectorscale StreamingDiskANN with label filtering; fall back to pgvector HNSW.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS tool_behavior_emb_diskann ON tooltruth.tool_behavior USING diskann (embedding vector_cosine_ops, labels)';
  ELSE
    EXECUTE 'CREATE INDEX IF NOT EXISTS tool_behavior_emb_hnsw ON tooltruth.tool_behavior USING hnsw (embedding vector_cosine_ops)';
  END IF;
END $$;
