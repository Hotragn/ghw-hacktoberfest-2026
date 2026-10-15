SET search_path TO witness, public;
-- Raw life memory compresses after 30 days and drops after 400; aggregates (habits) outlive raw rows.
ALTER TABLE life_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'user_id', timescaledb.compress_orderby = 'ts DESC');
SELECT add_compression_policy('witness.life_events', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('witness.life_events', INTERVAL '400 days', if_not_exists => TRUE);
SELECT add_retention_policy('witness.inbound', INTERVAL '90 days', if_not_exists => TRUE);
ALTER TABLE actions SET (timescaledb.compress, timescaledb.compress_segmentby = 'user_id', timescaledb.compress_orderby = 'ts DESC');
SELECT add_compression_policy('witness.actions', INTERVAL '60 days', if_not_exists => TRUE);
-- receipts: no retention policy, ever.
