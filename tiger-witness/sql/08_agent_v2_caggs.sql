SET search_path TO witness, public;
-- Habits: a continuous aggregate over episodic memory (what the user asks for, when, through which tools).
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS habits_daily WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS bucket, user_id, kind, coalesce(tool, '-') AS tool, channel,
       count(*) AS n, count(*) FILTER (WHERE tainted) AS n_tainted
FROM witness.agent_events GROUP BY 1,2,3,4,5 WITH NO DATA;
-- @@
SELECT add_continuous_aggregate_policy('witness.habits_daily', start_offset => INTERVAL '90 days', end_offset => NULL,
                                       schedule_interval => INTERVAL '10 minutes', if_not_exists => TRUE);
-- @@
SELECT add_retention_policy('witness.agent_events', INTERVAL '400 days', if_not_exists => TRUE);
-- @@
CREATE OR REPLACE VIEW witness.my_agent_events WITH (security_barrier) AS
SELECT * FROM witness.agent_events WHERE user_id = witness.current_uid();
-- @@
CREATE OR REPLACE VIEW witness.my_habits WITH (security_barrier) AS
SELECT * FROM witness.habits_daily WHERE user_id = witness.current_uid();
