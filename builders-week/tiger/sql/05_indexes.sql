-- Vector indexes: prefer pgvectorscale DiskANN; fall back to pgvector HNSW.
SET search_path TO builders_week, public;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    EXECUTE $idx$
      CREATE INDEX IF NOT EXISTS alert_embeddings_diskann
        ON builders_week.alert_embeddings
        USING diskann (embedding vector_cosine_ops)
    $idx$;
    RAISE NOTICE 'Using pgvectorscale DiskANN index on alert_embeddings.embedding';
  ELSE
    EXECUTE $idx$
      CREATE INDEX IF NOT EXISTS alert_embeddings_hnsw
        ON builders_week.alert_embeddings
        USING hnsw (embedding vector_cosine_ops)
    $idx$;
    RAISE NOTICE 'vectorscale missing; created pgvector HNSW index instead';
  END IF;
END $$;
