-- Least-privilege runtime roles. Run once as the owner after migrations:
--   psql "$ADMIN_URL" -v api_password="'...'" -v ingest_password="'...'" -f sql/roles.sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scamshield_api') THEN CREATE ROLE scamshield_api LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='scamshield_ingest') THEN CREATE ROLE scamshield_ingest LOGIN; END IF;
END $$;
ALTER ROLE scamshield_api PASSWORD :api_password;
ALTER ROLE scamshield_ingest PASSWORD :ingest_password;
GRANT USAGE ON SCHEMA scamshield TO scamshield_api, scamshield_ingest;
-- API: read everything, change consent ONLY through the audited functions (which run as owner).
GRANT SELECT ON ALL TABLES IN SCHEMA scamshield TO scamshield_api;
ALTER FUNCTION scamshield.revoke_consent(text, text) SECURITY DEFINER SET search_path = scamshield, public;
ALTER FUNCTION scamshield.pause_monitoring(text, text, interval) SECURITY DEFINER SET search_path = scamshield, public;
REVOKE EXECUTE ON FUNCTION scamshield.revoke_consent(text, text), scamshield.pause_monitoring(text, text, interval) FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA scamshield TO scamshield_api;
-- simulator / detector: append-only
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA scamshield TO scamshield_ingest;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA scamshield TO scamshield_ingest;
GRANT EXECUTE ON FUNCTION scamshield.consent_allows(text, text), scamshield.risk_features(text, interval),
  scamshield.fake_profit_screens(interval, float8), scamshield.similar_storylines TO scamshield_ingest;
