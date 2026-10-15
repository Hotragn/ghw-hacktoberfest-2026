SET search_path TO tooltruth, public;
-- Reusable queries packaged as SQL functions (callable from psql, the API, or the Tiger MCP db_query tool).

-- 1) Tool health over a window, from the continuous aggregate
CREATE OR REPLACE FUNCTION tool_health(p_since INTERVAL DEFAULT '24 hours')
RETURNS TABLE(tool TEXT, calls BIGINT, error_rate FLOAT8, p95_latency_ms FLOAT8, cost_per_success FLOAT8)
LANGUAGE sql STABLE AS $$
  SELECT tool, sum(calls)::bigint, sum(errors)::float8 / NULLIF(sum(calls),0),
         max(p95_latency_ms), sum(cost_usd) / NULLIF(sum(calls - errors),0)
  FROM tooltruth.tool_hourly WHERE bucket > now() - p_since
  GROUP BY tool ORDER BY 2 DESC $$;

-- 2) New destinations: hosts a tool started talking to in the recent window but never in the baseline
CREATE OR REPLACE FUNCTION new_destinations(p_recent INTERVAL DEFAULT '6 hours', p_baseline INTERVAL DEFAULT '7 days')
RETURNS TABLE(tool TEXT, dest TEXT, calls BIGINT, bytes NUMERIC, orgs BIGINT, first_bucket TIMESTAMPTZ)
LANGUAGE sql STABLE AS $$
  SELECT r.tool, r.dest, sum(r.calls)::bigint, sum(r.bytes), max(r.orgs)::bigint, min(r.bucket)
  FROM tooltruth.tool_dest_hourly r
  WHERE r.bucket > now() - p_recent
    AND NOT EXISTS (SELECT 1 FROM tooltruth.tool_dest_hourly b
                    WHERE b.tool = r.tool AND b.dest = r.dest
                      AND b.bucket <= now() - p_recent AND b.bucket > now() - p_baseline)
  GROUP BY r.tool, r.dest ORDER BY 4 DESC $$;

-- 3) "Tools behaving like known-bad": filtered vector similarity (time window + namespace + max distance)
CREATE OR REPLACE FUNCTION behaving_like_known_bad(p_since INTERVAL DEFAULT '24 hours',
                                                   p_namespace TEXT DEFAULT NULL,
                                                   p_max_distance FLOAT8 DEFAULT 0.05,
                                                   p_limit INT DEFAULT 20)
RETURNS TABLE(tool TEXT, namespace TEXT, window_end TIMESTAMPTZ, version TEXT, nearest_bad TEXT, distance FLOAT8)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT ON (t.tool) t.tool, t.namespace, t.window_end, t.version, kb.note, kb.dist
  FROM tooltruth.tool_behavior t
  CROSS JOIN LATERAL (
      SELECT b.note, (b.embedding <=> t.embedding) AS dist
      FROM tooltruth.tool_behavior b WHERE b.known_bad
      ORDER BY b.embedding <=> t.embedding LIMIT 1) kb
  WHERE NOT t.known_bad
    AND t.window_end > now() - p_since
    AND (p_namespace IS NULL OR t.namespace = p_namespace)
    AND kb.dist <= p_max_distance
  ORDER BY t.tool, kb.dist
  LIMIT p_limit $$;

-- 4) Latest ETH-USD price (used to value on-chain fees)
CREATE OR REPLACE FUNCTION latest_price(p_symbol TEXT)
RETURNS FLOAT8 LANGUAGE sql STABLE AS $$
  SELECT price FROM tooltruth.prices WHERE symbol = p_symbol ORDER BY ts DESC LIMIT 1 $$;

-- 5) Cost leaderboard per org
CREATE OR REPLACE FUNCTION org_spend(p_since INTERVAL DEFAULT '24 hours')
RETURNS TABLE(org TEXT, calls BIGINT, cost_usd FLOAT8)
LANGUAGE sql STABLE AS $$
  SELECT org, sum(calls)::bigint, sum(cost_usd) FROM tooltruth.org_tool_hourly
  WHERE bucket > now() - p_since GROUP BY org ORDER BY 3 DESC $$;
