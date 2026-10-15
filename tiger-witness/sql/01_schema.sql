-- Witness: a personal agent that can prove every action. ALL DATA IS SIMULATED.
SET search_path TO witness, public;

CREATE TABLE IF NOT EXISTS users (
  user_id       text PRIMARY KEY,
  display_name  text NOT NULL,
  home_channel  text NOT NULL,               -- where the user already talks: sms | whatsapp | slack | imessage
  timezone      text NOT NULL DEFAULT 'America/New_York',
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Mandates: the user's delegated authority, scoped and revocable (AP2-style "intent mandate", but local + queryable)
CREATE TABLE IF NOT EXISTS mandates (
  mandate_id    text PRIMARY KEY,
  user_id       text NOT NULL REFERENCES users,
  kind          text NOT NULL CHECK (kind IN ('one_time','standing')),
  action        text NOT NULL,               -- pay_bill | cancel_subscription | purchase | book | disclose | reply
  counterparty  text NOT NULL DEFAULT '*',   -- merchant/person glob; '*' = any
  max_amount    numeric(12,2),               -- per-action ceiling
  monthly_cap   numeric(12,2),               -- rolling 30-day ceiling across actions under this mandate
  disclose      text[] NOT NULL DEFAULT '{}',-- data classes the agent may reveal under this mandate
  uses_left     int,                         -- NULL = unlimited
  daily_action_budget int,                   -- consent-drift guard for standing mandates
  expires_at    timestamptz,
  revoked_at    timestamptz,
  note          text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Time-series memory of the user's life (simulated connectors): txns, bills, subscriptions, calendar, messages
CREATE TABLE IF NOT EXISTS life_events (
  ts          timestamptz NOT NULL,
  user_id     text NOT NULL,
  event_id    bigint GENERATED ALWAYS AS IDENTITY,
  kind        text NOT NULL,                 -- txn | bill | subscription | calendar | message | location
  merchant    text,
  category    text,
  amount      numeric(12,2),
  simulated   boolean NOT NULL DEFAULT true,
  detail      jsonb NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('witness.life_events', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS life_events_user_merchant ON life_events (user_id, merchant, ts DESC);
CREATE INDEX IF NOT EXISTS life_events_event_id ON life_events (event_id);

-- Tool registry with reputation imported from a ToolTruth-style cross-org fingerprinting feed
CREATE TABLE IF NOT EXISTS tools (
  tool_id     text PRIMARY KEY,
  capability  text NOT NULL,                 -- payments | email | calendar | marketplace | browser | phone
  publisher   text NOT NULL,
  reputation  real NOT NULL,                 -- 0..1
  drift_flag  boolean NOT NULL DEFAULT false,-- behaviour changed vs fleet fingerprint
  irreversible boolean NOT NULL DEFAULT false,
  checked_at  timestamptz NOT NULL DEFAULT now()
);

-- Inbound messages from third parties (ScamShield-style check before the agent acts on them)
CREATE TABLE IF NOT EXISTS inbound (
  ts           timestamptz NOT NULL,
  user_id      text NOT NULL,
  inbound_id   bigint GENERATED ALWAYS AS IDENTITY,
  channel      text NOT NULL,
  sender       text NOT NULL,
  body         text NOT NULL,
  scam_score   real,
  nearest      text
);
SELECT create_hypertable('witness.inbound', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);

-- Every agent decision. `context` is the full frozen input to the policy engine -> deterministic replay.
CREATE TABLE IF NOT EXISTS actions (
  ts           timestamptz NOT NULL,
  action_id    uuid NOT NULL,
  user_id      text NOT NULL,
  request      text NOT NULL,
  source       text NOT NULL DEFAULT 'user',  -- user | inbound:<id> | schedule
  intent       jsonb NOT NULL,
  context      jsonb NOT NULL,
  evidence     bigint[] NOT NULL DEFAULT '{}', -- life_events.event_id rows the plan relied on
  assumptions  jsonb NOT NULL DEFAULT '[]',    -- facts the planner needed but could NOT cite
  decision     text NOT NULL CHECK (decision IN ('executed_simulated','needs_approval','blocked')),
  reasons      jsonb NOT NULL,
  mandate_id   text,
  tool_id      text,
  merchant     text,
  amount       numeric(12,2),
  policy_version text NOT NULL
);
SELECT create_hypertable('witness.actions', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS actions_user_ts ON actions (user_id, ts DESC);

-- Receipts: append-only, hash-chained per user, HMAC-signed. Never compressed away, never updated.
CREATE TABLE IF NOT EXISTS receipts (
  user_id     text NOT NULL,
  seq         bigint NOT NULL,
  ts          timestamptz NOT NULL,
  action_id   uuid NOT NULL,
  payload     jsonb NOT NULL,
  prev_hash   text NOT NULL,
  hash        text NOT NULL,
  signature   text NOT NULL,
  PRIMARY KEY (user_id, seq)
);
CREATE OR REPLACE FUNCTION receipts_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'receipts are append-only (% blocked)', TG_OP; END $$;
DROP TRIGGER IF EXISTS receipts_no_mutation ON receipts;
CREATE TRIGGER receipts_no_mutation BEFORE UPDATE OR DELETE ON receipts
  FOR EACH ROW EXECUTE FUNCTION receipts_append_only();
