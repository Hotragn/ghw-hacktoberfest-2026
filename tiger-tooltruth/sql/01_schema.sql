SET search_path TO tooltruth, public;

CREATE TABLE IF NOT EXISTS tools (
  tool        TEXT PRIMARY KEY,           -- e.g. github.create_issue
  namespace   TEXT NOT NULL,              -- e.g. github
  publisher   TEXT NOT NULL,
  first_seen  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hypertable (TimescaleDB >= 2.20 CREATE TABLE ... WITH tsdb.* syntax).
-- Columnstore is enabled automatically, segmented by tool for fast per-tool scans.
CREATE TABLE IF NOT EXISTS tool_calls (
  ts            TIMESTAMPTZ NOT NULL,
  agent         TEXT NOT NULL,
  org           TEXT NOT NULL,
  tool          TEXT NOT NULL,
  version       TEXT NOT NULL,
  latency_ms    DOUBLE PRECISION NOT NULL,
  status        TEXT NOT NULL,             -- ok | error | timeout
  bytes_out     BIGINT NOT NULL,
  destinations  TEXT[] NOT NULL,
  model         TEXT,                      -- LLM model that drove the call (priced via OpenRouter)
  tokens_in     INT NOT NULL DEFAULT 0,
  tokens_out    INT NOT NULL DEFAULT 0,
  cost_usd      DOUBLE PRECISION NOT NULL  -- LLM cost + on-chain fee (ETH valued at live Coinbase price)
) WITH (
  tsdb.hypertable,
  tsdb.partition_column = 'ts',
  tsdb.chunk_interval = '1 day',
  tsdb.segmentby = 'tool',
  tsdb.orderby = 'ts DESC'
);
CREATE INDEX IF NOT EXISTS tool_calls_tool_ts ON tool_calls (tool, ts DESC);
CREATE INDEX IF NOT EXISTS tool_calls_org_ts ON tool_calls (org, ts DESC);

-- One row per (call, destination): lets a continuous aggregate count destinations.
CREATE TABLE IF NOT EXISTS call_destinations (
  ts    TIMESTAMPTZ NOT NULL,
  tool  TEXT NOT NULL,
  org   TEXT NOT NULL,
  dest  TEXT NOT NULL,
  bytes BIGINT NOT NULL
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'tool', tsdb.orderby = 'ts DESC');

-- Live price feed: OpenRouter model prices (USD/token) and Coinbase ETH-USD ticks.
CREATE TABLE IF NOT EXISTS prices (
  ts      TIMESTAMPTZ NOT NULL,
  source  TEXT NOT NULL,     -- coinbase | openrouter
  symbol  TEXT NOT NULL,     -- ETH-USD | <model id>:prompt | <model id>:completion
  price   DOUBLE PRECISION NOT NULL
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'symbol', tsdb.orderby = 'ts DESC');
CREATE INDEX IF NOT EXISTS prices_symbol_ts ON prices (symbol, ts DESC);

-- Behaviour fingerprints (16-dim numeric feature vector, see fingerprint.py).
CREATE TABLE IF NOT EXISTS tool_behavior (
  id          BIGSERIAL PRIMARY KEY,
  tool        TEXT NOT NULL,
  namespace   TEXT NOT NULL,
  ns_label    SMALLINT NOT NULL,          -- numeric namespace label for diskann label filtering
  labels      SMALLINT[] NOT NULL,
  window_end  TIMESTAMPTZ NOT NULL,
  version     TEXT,
  known_bad   BOOLEAN NOT NULL DEFAULT false,
  note        TEXT,
  embedding   vector(16) NOT NULL
);
CREATE INDEX IF NOT EXISTS tool_behavior_tool_ts ON tool_behavior (tool, window_end DESC);
