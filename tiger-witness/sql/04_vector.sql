SET search_path TO witness, public;
CREATE TABLE IF NOT EXISTS memories (
  memory_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     text NOT NULL,
  ts          timestamptz NOT NULL,
  kind        text NOT NULL,
  data_class  text NOT NULL DEFAULT 'personal', -- public | personal | financial | address | health
  text        text NOT NULL,
  source_event_id bigint,
  embedding   vector(256) NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_user ON memories (user_id, kind, ts DESC);
CREATE TABLE IF NOT EXISTS scam_storylines (
  storyline_id text PRIMARY KEY,
  title        text NOT NULL,
  is_scam      boolean NOT NULL,
  text         text NOT NULL,
  embedding    vector(256) NOT NULL
);
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS memories_emb_diskann ON witness.memories USING diskann (embedding vector_cosine_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS storylines_emb_diskann ON witness.scam_storylines USING diskann (embedding vector_cosine_ops)';
  ELSE
    EXECUTE 'CREATE INDEX IF NOT EXISTS memories_emb_hnsw ON witness.memories USING hnsw (embedding vector_cosine_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS storylines_emb_hnsw ON witness.scam_storylines USING hnsw (embedding vector_cosine_ops)';
  END IF;
END $$;
