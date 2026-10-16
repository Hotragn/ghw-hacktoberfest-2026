-- v3.1: zero-friction model router. Durable per-user / per-provider / pool daily LLM counters and first-seen
-- timestamps (new-user reserve). Shared by the API and every worker so budgets hold across replicas and restarts.
SET search_path = witness, public;
CREATE TABLE IF NOT EXISTS llm_usage (
  subject   text   NOT NULL,          -- 'pool' | 'user:<id>' | 'prov:<provider>/<model>'
  day       date   NOT NULL,          -- UTC day; provider free tiers reset at UTC midnight
  requests  int    NOT NULL DEFAULT 0,
  tokens    bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (subject, day)
);
CREATE TABLE IF NOT EXISTS llm_users (
  user_id    text PRIMARY KEY,
  first_seen timestamptz NOT NULL DEFAULT now()
);
-- turns parked because every provider was out of quota are 'deferred' (re-run from the durable queue)
ALTER TABLE agent_tasks DROP CONSTRAINT IF EXISTS agent_tasks_status_check;
ALTER TABLE agent_tasks ADD CONSTRAINT agent_tasks_status_check
  CHECK (status IN ('running','waiting_approval','done','failed','deferred'));
CREATE INDEX IF NOT EXISTS jobs_deferred_by_user ON jobs ((payload->>'user_id')) WHERE status = 'queued' AND queue = 'deferred';
