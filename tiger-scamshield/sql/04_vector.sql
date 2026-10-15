SET search_path TO scamshield, public;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS storylines_emb_diskann ON scamshield.scam_storylines USING diskann (embedding vector_cosine_ops, labels)';
  ELSE
    EXECUTE 'CREATE INDEX IF NOT EXISTS storylines_emb_hnsw ON scamshield.scam_storylines USING hnsw (embedding vector_cosine_ops)';
  END IF;
END $$;
