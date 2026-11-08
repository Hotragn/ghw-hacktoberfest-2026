-- Vector indexes: DiskANN when pgvectorscale is installed; otherwise HNSW with explicit WARNING.
SET search_path TO builders_week, public;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    EXECUTE $idx$
      CREATE INDEX IF NOT EXISTS alert_embeddings_diskann
        ON builders_week.alert_embeddings
        USING diskann (embedding vector_cosine_ops)
    $idx$;
    RAISE NOTICE 'pgvectorscale DiskANN index created on alert_embeddings.embedding';
  ELSE
    RAISE WARNING 'pgvectorscale extension is NOT installed — Challenge 5 vectorscale evidence requires Tiger Cloud (or manual CREATE EXTENSION vectorscale); using pgvector HNSW fallback';
    EXECUTE $idx$
      CREATE INDEX IF NOT EXISTS alert_embeddings_hnsw
        ON builders_week.alert_embeddings
        USING hnsw (embedding vector_cosine_ops)
    $idx$;
  END IF;
END $$;
