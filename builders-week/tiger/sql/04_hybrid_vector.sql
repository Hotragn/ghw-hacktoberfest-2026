-- Challenge 5: vectors alongside time-series data (hypertable). vector(256) NON-SEMANTIC demo.
SET search_path TO builders_week, public;

-- Fail closed on incompatible existing schema — operator must migrate manually.
DO $$
DECLARE
  dim integer;
BEGIN
  IF to_regclass('builders_week.alert_embeddings') IS NOT NULL THEN
    SELECT a.atttypmod INTO dim
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'builders_week'
      AND c.relname = 'alert_embeddings'
      AND a.attname = 'embedding'
      AND NOT a.attisdropped;
    -- pgvector: atttypmod is the dimension (see pgvector vector_typmod_in).
    IF dim IS NOT NULL AND dim <> 256 THEN
      RAISE EXCEPTION
        'builders_week.alert_embeddings.embedding must be vector(256) (atttypmod=%), found %. Manual operator migration required.',
        256, dim;
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
  -- NULL = non-fixture application row; demo imports set bw2026-demo-v1 explicitly (no DEFAULT).
  fixture_batch TEXT NULL,
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

CREATE UNIQUE INDEX IF NOT EXISTS alert_embeddings_recorded_fixture_uidx
  ON alert_embeddings (recorded_at, fixture_key);

CREATE INDEX IF NOT EXISTS alert_embeddings_site_sev_ts
  ON alert_embeddings (site, severity, recorded_at DESC);

COMMENT ON COLUMN alert_embeddings.embedding IS
  '256-d lexical hash demo (NON-SEMANTIC). External CSV: validate_embedding_csv.py';
