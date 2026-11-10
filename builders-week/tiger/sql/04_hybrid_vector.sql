-- Challenge 5: semantic embeddings (all-MiniLM-L6-v2, 384-d) alongside time-series hypertable.
SET search_path TO builders_week, public;

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
    IF dim IS NOT NULL AND dim <> 384 THEN
      RAISE EXCEPTION
        'builders_week.alert_embeddings.embedding must be vector(384) (atttypmod=%), found %. Manual operator migration required.',
        384, dim;
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
  fixture_batch TEXT NULL,
  embedding     vector(384) NOT NULL
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM timescaledb_information.hypertables
    WHERE hypertable_schema = 'builders_week' AND hypertable_name = 'alert_embeddings'
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
  'Semantic vector(384) from sentence-transformers/all-MiniLM-L6-v2 via scripts/embed_semantic.py';
