SET search_path TO tooltruth, public;
-- Refresh policies (idempotent via if_not_exists)
SELECT add_continuous_aggregate_policy('tool_hourly',      start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '5 minutes', if_not_exists => true);
SELECT add_continuous_aggregate_policy('org_tool_hourly',  start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '5 minutes', if_not_exists => true);
SELECT add_continuous_aggregate_policy('tool_dest_hourly', start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '5 minutes', if_not_exists => true);
SELECT add_continuous_aggregate_policy('eth_usd_1m',       start_offset => INTERVAL '1 day',  end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute',  if_not_exists => true);

-- Columnstore (compression): tsdb.hypertable already created a default policy; make the interval explicit.
CALL remove_columnstore_policy('tool_calls', if_exists => true);
CALL add_columnstore_policy('tool_calls', after => INTERVAL '2 days');
CALL remove_columnstore_policy('call_destinations', if_exists => true);
CALL add_columnstore_policy('call_destinations', after => INTERVAL '2 days');
CALL remove_columnstore_policy('prices', if_exists => true);
CALL add_columnstore_policy('prices', after => INTERVAL '1 day');

-- Columnstore on a continuous aggregate
ALTER MATERIALIZED VIEW tool_hourly SET (timescaledb.enable_columnstore = true, timescaledb.segmentby = 'tool');
CALL remove_columnstore_policy('tool_hourly', if_exists => true);
CALL add_columnstore_policy('tool_hourly', after => INTERVAL '7 days');

-- Retention: raw data 30 days, rollups 1 year
SELECT add_retention_policy('tool_calls',        drop_after => INTERVAL '30 days', if_not_exists => true);
SELECT add_retention_policy('call_destinations', drop_after => INTERVAL '30 days', if_not_exists => true);
SELECT add_retention_policy('prices',            drop_after => INTERVAL '90 days', if_not_exists => true);
SELECT add_retention_policy('tool_hourly',       drop_after => INTERVAL '365 days', if_not_exists => true);
