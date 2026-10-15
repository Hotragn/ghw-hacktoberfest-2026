SET search_path TO tooltruth, public;
-- Each continuous aggregate is its own statement batch (the loader splits on the double-dash-at-at marker lines).
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS tool_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', ts) AS bucket,
       tool,
       count(*)                                              AS calls,
       count(*) FILTER (WHERE status <> 'ok')                AS errors,
       count(*) FILTER (WHERE status <> 'ok')::float / count(*) AS error_rate,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms,
       avg(bytes_out)                                        AS avg_bytes_out,
       sum(cost_usd)                                         AS cost_usd,
       sum(cost_usd) / NULLIF(count(*) FILTER (WHERE status = 'ok'), 0) AS cost_per_success,
       max(version)                                          AS max_version
FROM tool_calls
GROUP BY bucket, tool
WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS org_tool_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', ts) AS bucket, org, tool,
       count(*) AS calls,
       count(*) FILTER (WHERE status <> 'ok') AS errors,
       sum(cost_usd) AS cost_usd
FROM tool_calls GROUP BY bucket, org, tool
WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS tool_dest_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', ts) AS bucket, tool, dest,
       count(*) AS calls, sum(bytes) AS bytes, count(DISTINCT org) AS orgs
FROM call_destinations GROUP BY bucket, tool, dest
WITH NO DATA;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS eth_usd_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 minute', ts) AS bucket, symbol,
       first(price, ts) AS open, max(price) AS high, min(price) AS low, last(price, ts) AS close, count(*) AS ticks
FROM prices WHERE source = 'coinbase' GROUP BY bucket, symbol
WITH NO DATA;
