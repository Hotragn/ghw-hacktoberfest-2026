-- Least-privilege runtime roles. Run once as the owner after migrations:
--   psql "$ADMIN_URL" -v api_password="'...'" -v ingest_password="'...'" -f sql/roles.sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='tooltruth_api') THEN CREATE ROLE tooltruth_api LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='tooltruth_ingest') THEN CREATE ROLE tooltruth_ingest LOGIN; END IF;
END $$;
ALTER ROLE tooltruth_api PASSWORD :api_password;
ALTER ROLE tooltruth_ingest PASSWORD :ingest_password;
GRANT USAGE ON SCHEMA tooltruth TO tooltruth_api, tooltruth_ingest;
-- dashboard/API: read-only
GRANT SELECT ON ALL TABLES IN SCHEMA tooltruth TO tooltruth_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA tooltruth TO tooltruth_api;
-- simulator / collectors / fingerprint job: append-only writes
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA tooltruth TO tooltruth_ingest;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA tooltruth TO tooltruth_ingest;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA tooltruth TO tooltruth_ingest;
