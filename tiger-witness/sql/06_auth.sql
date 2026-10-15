SET search_path TO witness, public;
-- Per-user accounts and server-side sessions. Only scrypt hashes / token sha256 are stored.
CREATE TABLE IF NOT EXISTS accounts (
  user_id     text PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  email       text NOT NULL,
  pw_hash     text NOT NULL,
  failed_logins int NOT NULL DEFAULT 0,
  locked_until  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_email ON accounts (lower(email));
CREATE TABLE IF NOT EXISTS sessions (
  token_sha256 text PRIMARY KEY,
  user_id      text NOT NULL REFERENCES users ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  ip           text,
  user_agent   text
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);
-- Pending approvals: a needs_approval action can be approved/denied once, by its owner, and both outcomes are receipted.
CREATE TABLE IF NOT EXISTS approvals (
  action_id   uuid PRIMARY KEY,
  user_id     text NOT NULL,
  outcome     text NOT NULL CHECK (outcome IN ('approved','denied')),
  decided_at  timestamptz NOT NULL DEFAULT now()
);
