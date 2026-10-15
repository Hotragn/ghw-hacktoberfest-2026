SET search_path TO scamshield, public;
-- ALL DATA IS SIMULATED. No real people, devices, accounts or messages.

-- Consent is first-class: nothing is ingested or alerted without an active, scoped consent.
CREATE TABLE IF NOT EXISTS households (
  household_id      TEXT PRIMARY KEY,
  display_name      TEXT NOT NULL,
  tz                TEXT NOT NULL DEFAULT 'America/New_York',
  consent_status    TEXT NOT NULL DEFAULT 'pending' CHECK (consent_status IN ('pending','active','paused','revoked')),
  consent_scopes    TEXT[] NOT NULL DEFAULT '{}',   -- calls, door, sleep, location, transactions, screens, alerts
  paused_until      TIMESTAMPTZ,
  trusted_contact   TEXT,                           -- name only; delivery is simulated
  consented_by      TEXT,                           -- the elder themself (not the family member)
  consented_at      TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS consent_log (
  ts TIMESTAMPTZ NOT NULL DEFAULT now(), household_id TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, scopes TEXT[], note TEXT
);

-- Sensor-style home signals (IoT dataset + metadata)
CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households,
  kind TEXT NOT NULL, model TEXT, room TEXT, installed_at TIMESTAMPTZ, firmware TEXT
);
CREATE TABLE IF NOT EXISTS home_signals (
  ts            TIMESTAMPTZ NOT NULL,
  household_id  TEXT NOT NULL,
  device_id     TEXT NOT NULL,
  kind          TEXT NOT NULL,     -- call | door | sleep | location
  value         DOUBLE PRECISION,  -- call minutes | door open secs | sleep disruption 0..1 | dwell minutes
  local_hour    SMALLINT NOT NULL,
  meta          JSONB NOT NULL DEFAULT '{}'   -- e.g. {"caller":"unknown","intl":true} / {"place":"crypto_kiosk"}
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.chunk_interval = '1 day',
        tsdb.segmentby = 'household_id', tsdb.orderby = 'ts DESC');
CREATE INDEX IF NOT EXISTS home_signals_hh_kind_ts ON home_signals (household_id, kind, ts DESC);

CREATE TABLE IF NOT EXISTS transactions (
  ts            TIMESTAMPTZ NOT NULL,
  household_id  TEXT NOT NULL,
  kind          TEXT NOT NULL,     -- groceries | pharmacy | atm | crypto_kiosk | wire | gift_card | utility
  amount_usd    DOUBLE PRECISION NOT NULL,
  btc_amount    DOUBLE PRECISION,  -- for crypto kiosk deposits
  btc_usd       DOUBLE PRECISION,  -- live Coinbase BTC-USD at tx time
  counterparty  TEXT
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'household_id', tsdb.orderby = 'ts DESC');

-- What the scam "investment app" showed on the elder's screen (simulated OCR of a consented screen share)
CREATE TABLE IF NOT EXISTS profit_claims (
  ts                 TIMESTAMPTZ NOT NULL,
  household_id       TEXT NOT NULL,
  app_name           TEXT NOT NULL,
  claimed_btc_usd    DOUBLE PRECISION NOT NULL,
  claimed_balance_usd DOUBLE PRECISION NOT NULL,
  claimed_return_pct DOUBLE PRECISION NOT NULL
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'household_id');

CREATE TABLE IF NOT EXISTS btc_ticks (
  ts TIMESTAMPTZ NOT NULL, product TEXT NOT NULL, price DOUBLE PRECISION NOT NULL
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'product', tsdb.orderby = 'ts DESC');

-- Known scam storylines (RAG corpus) and per-household narrative snapshots
CREATE TABLE IF NOT EXISTS scam_storylines (
  id SERIAL PRIMARY KEY, title TEXT UNIQUE NOT NULL, category TEXT NOT NULL, cat_label SMALLINT NOT NULL,
  labels SMALLINT[] NOT NULL, story TEXT NOT NULL, advice TEXT NOT NULL, embedding vector(256) NOT NULL
);
CREATE TABLE IF NOT EXISTS case_snapshots (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(), household_id TEXT NOT NULL,
  narrative TEXT NOT NULL, embedding vector(256) NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(), household_id TEXT NOT NULL,
  risk_score DOUBLE PRECISION NOT NULL, reasons JSONB NOT NULL, storyline TEXT, distance DOUBLE PRECISION,
  delivery TEXT NOT NULL,   -- simulated_to_trusted_contact | suppressed_no_consent | suppressed_paused
  message TEXT NOT NULL
);
