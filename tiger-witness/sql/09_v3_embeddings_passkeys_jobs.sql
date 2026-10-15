-- Witness v3: pluggable embeddings of any dimension, WebAuthn passkeys bound to mandates/approvals, durable job queue.
-- Idempotent; Tiger Cloud compatible.
SET search_path TO witness, public;

-- ---------- embeddings: dimension-agnostic column + per-model partial expression indexes
CREATE TABLE IF NOT EXISTS embedding_models (
  model      text PRIMARY KEY,           -- e.g. 'local:sentence-transformers/all-MiniLM-L6-v2'
  dim        int  NOT NULL CHECK (dim BETWEEN 2 AND 4000),
  active     boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding_v vector;     -- untyped: any dimension
ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embed_model text;
ALTER TABLE memory_items ALTER COLUMN embedding DROP NOT NULL;            -- legacy 256-d hashed column
UPDATE memory_items SET embedding_v = embedding, embed_model = 'hashed-256'
  WHERE embedding_v IS NULL AND embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS memory_items_model ON memory_items (user_id, embed_model);

-- Build (once per model) an ANN index over embedding_v cast to that model's dimension, restricted to its rows.
-- DiskANN (pgvectorscale) on Tiger Cloud; HNSW (pgvector) elsewhere.
CREATE OR REPLACE FUNCTION witness.ensure_embedding_index(p_model text, p_dim int) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE idx text := 'memory_items_emb_' || substr(md5(p_model), 1, 10) || '_' || p_dim;
        meth text := CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname='vectorscale') THEN 'diskann' ELSE 'hnsw' END;
BEGIN
  IF p_dim < 2 OR p_dim > 4000 THEN RAISE EXCEPTION 'bad dim %', p_dim; END IF;
  INSERT INTO witness.embedding_models (model, dim) VALUES (p_model, p_dim) ON CONFLICT (model) DO NOTHING;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='witness' AND indexname=idx) THEN
    EXECUTE format('CREATE INDEX %I ON witness.memory_items USING %s ((embedding_v::vector(%s)) vector_cosine_ops) WHERE embed_model = %L',
                   idx, meth, p_dim, p_model);
  END IF;
  RETURN idx;
END $$;
SELECT witness.ensure_embedding_index('hashed-256', 256);

-- ---------- WebAuthn passkeys
CREATE TABLE IF NOT EXISTS webauthn_credentials (
  credential_id bytea PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  public_key  bytea NOT NULL,             -- COSE key
  sign_count  bigint NOT NULL DEFAULT 0,
  name        text NOT NULL DEFAULT 'passkey',
  transports  text[] NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz
);
CREATE INDEX IF NOT EXISTS webauthn_credentials_user ON webauthn_credentials (user_id);
CREATE TABLE IF NOT EXISTS webauthn_challenges (
  challenge_id uuid PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  purpose     text NOT NULL CHECK (purpose IN ('register','mandate','approval')),
  subject_id  text,                       -- mandate_id / approval_id
  bound_sha256 text,                      -- hash of the exact object being authorised
  challenge   bytea NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);
ALTER TABLE pay_mandates ADD COLUMN IF NOT EXISTS passkey_assertion jsonb;   -- offline-verifiable user signature
ALTER TABLE pay_mandates ADD COLUMN IF NOT EXISTS passkey_confirmed_at timestamptz;
ALTER TABLE pending_approvals ADD COLUMN IF NOT EXISTS risk text NOT NULL DEFAULT 'normal';
ALTER TABLE pending_approvals ADD COLUMN IF NOT EXISTS passkey_assertion jsonb;

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['webauthn_credentials','webauthn_challenges'] LOOP
    EXECUTE format('ALTER TABLE witness.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE witness.%I FORCE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='witness' AND tablename=t AND policyname='tenant_isolation') THEN
      EXECUTE format($p$CREATE POLICY tenant_isolation ON witness.%I USING (user_id = witness.current_uid()
        OR witness.current_uid() = '__system__') WITH CHECK (user_id = witness.current_uid() OR witness.current_uid() = '__system__')$p$, t);
    END IF;
  END LOOP;
END $$;

-- ---------- durable job queue (channel webhooks, re-embedding). Workers claim with FOR UPDATE SKIP LOCKED.
CREATE TABLE IF NOT EXISTS jobs (
  job_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  queue        text NOT NULL,
  payload      jsonb NOT NULL,
  dedupe_key   text UNIQUE,                -- e.g. telegram:update_id, whatsapp:wamid (webhook retries are no-ops)
  status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','dead')),
  attempts     int  NOT NULL DEFAULT 0,
  max_attempts int  NOT NULL DEFAULT 5,
  run_after    timestamptz NOT NULL DEFAULT now(),
  locked_at    timestamptz,
  locked_by    text,
  last_error   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  done_at      timestamptz
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (queue, run_after, job_id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS jobs_running ON jobs (locked_at) WHERE status = 'running';
