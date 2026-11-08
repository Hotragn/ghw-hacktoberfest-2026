-- Challenge 5: vectors alongside time-series data (hypertable). vector(256) NON-SEMANTIC demo.
SET search_path TO builders_week, public;

-- If a prior 16-d demo table exists in this schema, drop only that fixture table (builders_week scope).
DO $$
DECLARE
  dim integer;
BEGIN
  IF to_regclass('builders_week.alert_embeddings') IS NOT NULL THEN
    SELECT (a.atttypmod - 4) INTO dim
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'builders_week'
      AND c.relname = 'alert_embeddings'
      AND a.attname = 'embedding'
      AND NOT a.attisdropped;
    IF dim IS NOT NULL AND dim <> 256 THEN
      RAISE NOTICE 'Dropping builders_week.alert_embeddings (embedding dimension %, expected 256)', dim;
      DROP TABLE builders_week.alert_embeddings CASCADE;
    END IF;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS alert_embeddings (
  recorded_at   TIMESTAMPTZ NOT NULL,
  fixture_key   TEXT NOT NULL,
  device_id     TEXT NOT NULL,
  site          TEXT NOT NULL,
  category      TEXT NOT NULL,
  severity      SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
  summary_text  TEXT NOT NULL,
  tags          TEXT[] NOT NULL DEFAULT '{}',
  fixture_batch TEXT NOT NULL DEFAULT 'bw2026-demo-v1',
  -- Deterministic 256-d lexical feature hash — NOT semantic LLM embeddings (see README).
  embedding     vector(256) NOT NULL
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM timescaledb_information.hypertables
    WHERE hypertable_schema = 'builders_week'
      AND hypertable_name = 'alert_embeddings'
  ) THEN
    RAISE NOTICE 'alert_embeddings is already a hypertable';
  ELSE
    PERFORM create_hypertable(
      'builders_week.alert_embeddings',
      by_range('recorded_at', INTERVAL '7 days'),
      if_not_exists => TRUE
    );
  END IF;
END $$;

-- Hypertable unique indexes must include the partition time column.
CREATE UNIQUE INDEX IF NOT EXISTS alert_embeddings_recorded_fixture_uidx
  ON alert_embeddings (recorded_at, fixture_key);

CREATE INDEX IF NOT EXISTS alert_embeddings_site_sev_ts
  ON alert_embeddings (site, severity, recorded_at DESC);

COMMENT ON COLUMN alert_embeddings.embedding IS
  '256-d lexical hash demo only; replace with vetted external model embeddings + validate_embedding_csv.py if required.';
