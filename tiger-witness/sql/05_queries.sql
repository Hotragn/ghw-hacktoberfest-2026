SET search_path TO witness, public;

-- Filtered memory recall: vector similarity + kind/data-class/time filters in one query
CREATE OR REPLACE FUNCTION recall(p_user text, p_q vector, p_kinds text[] DEFAULT NULL,
                                  p_classes text[] DEFAULT NULL, p_since interval DEFAULT '400 days', p_k int DEFAULT 5)
RETURNS TABLE (memory_id bigint, ts timestamptz, kind text, data_class text, text text, source_event_id bigint, similarity real)
LANGUAGE sql STABLE AS $$
  SELECT m.memory_id, m.ts, m.kind, m.data_class, m.text, m.source_event_id, (1 - (m.embedding <=> p_q))::real
  FROM witness.memories m
  WHERE m.user_id = p_user AND m.ts > now() - p_since
    AND (p_kinds IS NULL OR m.kind = ANY(p_kinds))
    AND (p_classes IS NULL OR m.data_class = ANY(p_classes))
  ORDER BY m.embedding <=> p_q LIMIT p_k $$;

-- The user's own baseline for a merchant, from the monthly cagg (habit memory, not raw rows)
CREATE OR REPLACE FUNCTION merchant_baseline(p_user text, p_merchant text)
RETURNS TABLE (months int, median_monthly numeric, max_monthly numeric, last_charge numeric, last_ts timestamptz)
LANGUAGE sql STABLE AS $$
  WITH m AS (SELECT total FROM witness.spend_monthly WHERE user_id = p_user AND lower(merchant) = lower(p_merchant)
             AND bucket > now() - interval '365 days'),
       l AS (SELECT amount, ts FROM witness.life_events WHERE user_id = p_user AND lower(merchant) = lower(p_merchant)
             AND kind IN ('txn','bill','subscription') AND NOT (detail ? 'by_agent') ORDER BY ts DESC LIMIT 1)
  SELECT (SELECT count(*)::int FROM m),
         (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total)::numeric(12,2) FROM m),
         (SELECT max(total) FROM m), (SELECT amount FROM l), (SELECT ts FROM l) $$;

-- Subscriptions whose price crept up (agent proposes, user decides)
CREATE OR REPLACE FUNCTION subscription_creep(p_user text)
RETURNS TABLE (merchant text, first_price numeric, latest_price numeric, pct_change numeric, months int)
LANGUAGE sql STABLE AS $$
  SELECT merchant, first(amount, ts), last(amount, ts),
         round(100 * (last(amount, ts) / NULLIF(first(amount, ts),0) - 1), 1), count(*)::int
  FROM witness.life_events WHERE user_id = p_user AND kind = 'subscription'
  GROUP BY merchant HAVING last(amount, ts) > first(amount, ts) ORDER BY 4 DESC $$;

-- Subscriptions the user pays for but has not used in N days (usage events carry detail.usage)
CREATE OR REPLACE FUNCTION idle_subscriptions(p_user text, p_idle interval DEFAULT '60 days')
RETURNS TABLE (merchant text, monthly numeric, last_used timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT s.merchant, last(s.amount, s.ts),
         (SELECT max(u.ts) FROM witness.life_events u WHERE u.user_id = p_user AND u.merchant = s.merchant AND u.kind = 'usage')
  FROM witness.life_events s WHERE s.user_id = p_user AND s.kind = 'subscription' AND s.ts > now() - interval '45 days'
  GROUP BY s.merchant
  HAVING coalesce((SELECT max(u.ts) FROM witness.life_events u WHERE u.user_id = p_user AND u.merchant = s.merchant AND u.kind = 'usage'),
                  '-infinity') < now() - p_idle $$;

-- Consent drift: standing mandates whose autonomous use is growing beyond what the user set up
CREATE OR REPLACE FUNCTION consent_drift(p_user text, p_window interval DEFAULT '7 days')
RETURNS TABLE (mandate_id text, action text, budget int, peak_day int, recent bigint, prior bigint, growth numeric)
LANGUAGE sql STABLE AS $$
  WITH d AS (SELECT mandate_id, time_bucket('1 day', bucket) AS day, sum(n) AS n
             FROM witness.actions_hourly WHERE user_id = p_user AND decision = 'executed_simulated'
               AND bucket > now() - 2 * p_window GROUP BY 1,2)
  SELECT m.mandate_id, m.action, m.daily_action_budget,
         coalesce(max(d.n),0)::int,
         coalesce(sum(d.n) FILTER (WHERE d.day >  now() - p_window),0)::bigint,
         coalesce(sum(d.n) FILTER (WHERE d.day <= now() - p_window),0)::bigint,
         round(coalesce(sum(d.n) FILTER (WHERE d.day > now() - p_window),0)::numeric
               / GREATEST(coalesce(sum(d.n) FILTER (WHERE d.day <= now() - p_window),0),1), 2)
  FROM witness.mandates m LEFT JOIN d USING (mandate_id)
  WHERE m.user_id = p_user AND m.kind = 'standing' AND m.revoked_at IS NULL
  GROUP BY 1,2,3 ORDER BY 7 DESC $$;

-- Hash-chain integrity check in pure SQL (signature check happens in Python with the key)
CREATE OR REPLACE FUNCTION verify_chain(p_user text)
RETURNS TABLE (seq bigint, ok_link boolean, ok_hash boolean)
LANGUAGE sql STABLE AS $$
  SELECT r.seq,
         r.prev_hash = coalesce(lag(r.hash) OVER (ORDER BY r.seq), repeat('0',64)),
         r.hash = encode(sha256(convert_to(r.prev_hash || r.payload::text, 'UTF8')), 'hex')
  FROM witness.receipts r WHERE r.user_id = p_user ORDER BY r.seq $$;

-- Mandate spend in the last 30 days (raw actions; small table per user)
CREATE OR REPLACE FUNCTION mandate_spend_30d(p_mandate text)
RETURNS numeric LANGUAGE sql STABLE AS $$
  SELECT coalesce(sum(amount),0) FROM witness.actions
  WHERE mandate_id = p_mandate AND decision = 'executed_simulated' AND ts > now() - interval '30 days' $$;
