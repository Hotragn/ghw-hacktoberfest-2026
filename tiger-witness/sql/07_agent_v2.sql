-- Witness v2: task-executing agent. Episodic + semantic memory, consent grants, approvals, AP2-style payment
-- mandates, API tokens, channel links, MCP servers. Idempotent; Tiger Cloud compatible (TimescaleDB + pgvector).
-- Multi-tenant isolation: every v2 table has FORCE ROW LEVEL SECURITY keyed on the per-transaction GUC
-- witness.user_id (set by the app with set_config(..., true)). '__system__' is used only by channel routing.
SET search_path TO witness, public;

CREATE OR REPLACE FUNCTION witness.current_uid() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('witness.user_id', true), '') $$;

-- Agent tasks: one per conversation turn/goal; transcript kept for resumption after approval.
CREATE TABLE IF NOT EXISTS agent_tasks (
  task_id     uuid PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  channel     text NOT NULL DEFAULT 'web',
  lang        text NOT NULL DEFAULT 'en',
  goal        text NOT NULL,
  status      text NOT NULL CHECK (status IN ('running','waiting_approval','done','failed')),
  steps       int  NOT NULL DEFAULT 0,
  tainted     boolean NOT NULL DEFAULT false,
  transcript  jsonb NOT NULL DEFAULT '[]',
  result      text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_tasks_user ON agent_tasks (user_id, created_at DESC);

-- Episodic memory: append-only time series of everything the agent saw and did.
-- TimescaleDB cannot build a continuous aggregate on an RLS hypertable, so isolation here is via the
-- security_barrier views my_agent_events / my_habits (08); the app role gets INSERT on the table, SELECT on views only.
CREATE TABLE IF NOT EXISTS agent_events (
  ts        timestamptz NOT NULL,
  user_id   text NOT NULL,
  event_id  bigint GENERATED ALWAYS AS IDENTITY,
  task_id   uuid,
  kind      text NOT NULL,        -- user_msg | assistant_msg | tool_call | tool_result | gate | approval | memory
  tool      text,
  channel   text,
  lang      text,
  tainted   boolean NOT NULL DEFAULT false,
  content   jsonb NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('witness.agent_events', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS agent_events_user_task ON agent_events (user_id, task_id, ts);

-- Semantic memory: user-visible, editable, forgettable facts with pgvector embeddings.
CREATE TABLE IF NOT EXISTS memory_items (
  memory_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  kind        text NOT NULL DEFAULT 'fact' CHECK (kind IN ('fact','preference','person','place','episode')),
  text        text NOT NULL CHECK (length(text) BETWEEN 1 AND 2000),
  data_class  text NOT NULL DEFAULT 'personal',
  source      text NOT NULL DEFAULT 'user' CHECK (source IN ('user','agent','tool')),
  confidence  real NOT NULL DEFAULT 1.0,
  pinned      boolean NOT NULL DEFAULT false,
  embedding   vector(256) NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  expires_at  timestamptz
);
CREATE INDEX IF NOT EXISTS memory_items_user ON memory_items (user_id, updated_at DESC);
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS memory_items_emb_diskann ON witness.memory_items USING diskann (embedding vector_cosine_ops)';
  ELSE
    EXECUTE 'CREATE INDEX IF NOT EXISTS memory_items_emb_hnsw ON witness.memory_items USING hnsw (embedding vector_cosine_ops)';
  END IF;
END $$;
-- Forgetting leaves only a content hash (proof that something was deleted, never what).
CREATE TABLE IF NOT EXISTS memory_forget_log (
  user_id     text NOT NULL,
  memory_id   bigint NOT NULL,
  text_sha256 text NOT NULL,
  forgotten_at timestamptz NOT NULL DEFAULT now()
);

-- Consent grants: scoped, expiring, revocable, per tool pattern and data class.
CREATE TABLE IF NOT EXISTS grants (
  grant_id     uuid PRIMARY KEY,
  user_id      text NOT NULL REFERENCES users ON DELETE CASCADE,
  tool_pattern text NOT NULL,                       -- glob, e.g. 'calendar_*' or 'mcp:github/*'
  scopes       text[] NOT NULL DEFAULT '{read}',    -- read | write | spend
  data_classes text[] NOT NULL DEFAULT '{public,personal}',
  auto_approve boolean NOT NULL DEFAULT false,      -- write actions run without a human tap
  max_uses     int,
  uses         int NOT NULL DEFAULT 0,
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  note         text,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grants_user ON grants (user_id) WHERE revoked_at IS NULL;

-- Human-in-the-loop approvals for parked tool calls.
CREATE TABLE IF NOT EXISTS pending_approvals (
  approval_id uuid PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  task_id     uuid NOT NULL REFERENCES agent_tasks ON DELETE CASCADE,
  call_id     text NOT NULL,
  tool        text NOT NULL,
  args        jsonb NOT NULL,
  reasons     jsonb NOT NULL,
  status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','denied','expired')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  decided_at  timestamptz
);
CREATE INDEX IF NOT EXISTS pending_approvals_user ON pending_approvals (user_id, status, created_at DESC);

-- AP2-style open mandates (user-approved constraints) and closed, agent-signed checkout/payment records.
CREATE TABLE IF NOT EXISTS pay_mandates (
  mandate_id   text PRIMARY KEY,
  user_id      text NOT NULL REFERENCES users ON DELETE CASCADE,
  description  text NOT NULL,
  merchants    text[] NOT NULL,                      -- allowlist (exact or '*.domain' wildcard)
  currency     text NOT NULL DEFAULT 'USD',
  max_per_txn  numeric(12,2) NOT NULL CHECK (max_per_txn > 0),
  budget       numeric(12,2) NOT NULL CHECK (budget > 0),
  budget_window interval NOT NULL DEFAULT '30 days',
  human_present_required boolean NOT NULL DEFAULT false,
  content      jsonb NOT NULL,                       -- canonical open-mandate content (signed)
  user_signature text NOT NULL,                      -- HMAC by the trusted surface at creation (session-authenticated)
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payments (
  payment_id   uuid PRIMARY KEY,
  ts           timestamptz NOT NULL DEFAULT now(),
  user_id      text NOT NULL REFERENCES users ON DELETE CASCADE,
  mandate_id   text NOT NULL REFERENCES pay_mandates,
  merchant     text NOT NULL,
  amount       numeric(12,2) NOT NULL CHECK (amount > 0),
  currency     text NOT NULL,
  checkout     jsonb NOT NULL,
  checkout_hash text NOT NULL,
  closed_mandate jsonb NOT NULL,
  agent_signature text NOT NULL,                     -- ECDSA P-256 over the closed mandate
  rail         text NOT NULL,
  provider_ref text,
  status       text NOT NULL CHECK (status IN ('settled','failed','pending')),
  idempotency_key text NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS payments_mandate ON payments (mandate_id, ts DESC);

-- Personal API tokens (scoped, revocable) on top of browser sessions.
CREATE TABLE IF NOT EXISTS api_tokens (
  token_sha256 text PRIMARY KEY,
  user_id      text NOT NULL REFERENCES users ON DELETE CASCADE,
  name         text NOT NULL,
  scopes       text[] NOT NULL DEFAULT '{agent}',
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  last_used_at timestamptz
);

-- Messaging channels: users chat where they already are.
CREATE TABLE IF NOT EXISTS channel_links (
  channel     text NOT NULL,
  external_id text NOT NULL,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  linked_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (channel, external_id)
);
CREATE TABLE IF NOT EXISTS link_codes (
  code_sha256 text PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  channel     text NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);

-- MCP servers a user connected (any server speaking MCP over streamable HTTP or stdio).
CREATE TABLE IF NOT EXISTS mcp_servers (
  server_id   uuid PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users ON DELETE CASCADE,
  name        text NOT NULL CHECK (name ~ '^[a-z0-9_-]{1,32}$'),
  transport   text NOT NULL CHECK (transport IN ('http','stdio')),
  target      text NOT NULL,                          -- URL or command line
  auth_env    text,                                   -- NAME of env var holding a bearer token (never the secret)
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);

-- Connector settings (ICS/CalDAV/IMAP/SMTP). Secrets are referenced by env var name only.
CREATE TABLE IF NOT EXISTS connectors (
  user_id   text NOT NULL REFERENCES users ON DELETE CASCADE,
  kind      text NOT NULL CHECK (kind IN ('ics','caldav','imap','smtp')),
  config    jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, kind)
);

-- Row-level security (FORCE: applies to the table owner too; superusers still bypass).
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['agent_tasks','memory_items','memory_forget_log','grants','pending_approvals',
                           'pay_mandates','payments','api_tokens','channel_links','link_codes','mcp_servers','connectors'] LOOP
    EXECUTE format('ALTER TABLE witness.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE witness.%I FORCE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='witness' AND tablename=t AND policyname='tenant_isolation') THEN
      EXECUTE format($p$CREATE POLICY tenant_isolation ON witness.%I USING (user_id = witness.current_uid()
        OR witness.current_uid() = '__system__') WITH CHECK (user_id = witness.current_uid() OR witness.current_uid() = '__system__')$p$, t);
    END IF;
  END LOOP;
END $$;
