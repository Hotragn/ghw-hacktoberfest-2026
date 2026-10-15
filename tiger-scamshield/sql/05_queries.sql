SET search_path TO scamshield, public;

-- Consent gate used by ingestors and the detector
CREATE OR REPLACE FUNCTION consent_allows(p_hh TEXT, p_scope TEXT) RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT consent_status = 'active' AND p_scope = ANY(consent_scopes)
                          AND (paused_until IS NULL OR paused_until < now())
                   FROM scamshield.households WHERE household_id = p_hh), false) $$;

-- Off-switch: revoke = stop everything AND delete raw data for that household
CREATE OR REPLACE FUNCTION revoke_consent(p_hh TEXT, p_actor TEXT) RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE n BIGINT;
BEGIN
  UPDATE scamshield.households SET consent_status = 'revoked', consent_scopes = '{}' WHERE household_id = p_hh;
  DELETE FROM scamshield.home_signals  WHERE household_id = p_hh; GET DIAGNOSTICS n = ROW_COUNT;
  DELETE FROM scamshield.profit_claims WHERE household_id = p_hh;
  DELETE FROM scamshield.case_snapshots WHERE household_id = p_hh;
  INSERT INTO scamshield.consent_log(household_id, actor, action, note) VALUES (p_hh, p_actor, 'revoke', n || ' raw signals deleted');
  RETURN 'revoked; deleted ' || n || ' raw signals';
END $$;

CREATE OR REPLACE FUNCTION pause_monitoring(p_hh TEXT, p_actor TEXT, p_for INTERVAL) RETURNS VOID LANGUAGE sql AS $$
  UPDATE scamshield.households SET paused_until = now() + p_for WHERE household_id = p_hh;
  INSERT INTO scamshield.consent_log(household_id, actor, action, note) VALUES (p_hh, p_actor, 'pause', p_for::text) $$;

-- Risk features for a household from the continuous aggregates
CREATE OR REPLACE FUNCTION risk_features(p_hh TEXT, p_since INTERVAL DEFAULT '7 days')
RETURNS TABLE(night_call_minutes FLOAT8, intl_calls BIGINT, night_door_events BIGINT, sleep_disruption FLOAT8,
              kiosk_visits BIGINT, kiosk_usd FLOAT8, gift_card_usd FLOAT8, wire_usd FLOAT8)
LANGUAGE sql STABLE AS $$
  SELECT
    (SELECT coalesce(sum(night_call_minutes),0) FROM scamshield.signals_hourly WHERE household_id=p_hh AND kind='call' AND bucket > now()-p_since),
    (SELECT coalesce(sum(intl_events),0)::bigint FROM scamshield.signals_hourly WHERE household_id=p_hh AND kind='call' AND bucket > now()-p_since),
    (SELECT coalesce(sum(night_events),0)::bigint FROM scamshield.signals_hourly WHERE household_id=p_hh AND kind='door' AND bucket > now()-p_since),
    (SELECT coalesce(sum(total_value)/NULLIF(sum(events),0),0) FROM scamshield.signals_hourly WHERE household_id=p_hh AND kind='sleep' AND bucket > now()-p_since),
    (SELECT coalesce(sum(kiosk_visits),0)::bigint FROM scamshield.signals_hourly WHERE household_id=p_hh AND kind='location' AND bucket > now()-p_since),
    (SELECT coalesce(sum(usd),0) FROM scamshield.tx_daily WHERE household_id=p_hh AND kind='crypto_kiosk' AND bucket > now()-p_since),
    (SELECT coalesce(sum(usd),0) FROM scamshield.tx_daily WHERE household_id=p_hh AND kind='gift_card' AND bucket > now()-p_since),
    (SELECT coalesce(sum(usd),0) FROM scamshield.tx_daily WHERE household_id=p_hh AND kind='wire' AND bucket > now()-p_since) $$;

-- Fake-profit-screen detector: compare what the app claimed to the real Coinbase BTC price at that moment
CREATE OR REPLACE FUNCTION fake_profit_screens(p_since INTERVAL DEFAULT '7 days', p_min_gap_pct FLOAT8 DEFAULT 5)
RETURNS TABLE(ts TIMESTAMPTZ, household_id TEXT, app_name TEXT, claimed_btc_usd FLOAT8, real_btc_usd FLOAT8,
              gap_pct FLOAT8, claimed_return_pct FLOAT8)
LANGUAGE sql STABLE AS $$
  SELECT c.ts, c.household_id, c.app_name, c.claimed_btc_usd, r.price,
         100 * (c.claimed_btc_usd - r.price) / r.price, c.claimed_return_pct
  FROM scamshield.profit_claims c
  CROSS JOIN LATERAL (SELECT price FROM scamshield.btc_ticks b
                      WHERE b.product = 'BTC-USD' AND b.ts <= c.ts + interval '1 minute'
                      ORDER BY b.ts DESC LIMIT 1) r
  WHERE c.ts > now() - p_since
    AND abs(100 * (c.claimed_btc_usd - r.price) / r.price) >= p_min_gap_pct
  ORDER BY c.ts DESC $$;

-- RAG: storylines most similar to a household's latest narrative, filtered by category + distance
CREATE OR REPLACE FUNCTION similar_storylines(p_hh TEXT, p_category TEXT DEFAULT NULL,
                                              p_max_distance FLOAT8 DEFAULT 0.8, p_limit INT DEFAULT 3)
RETURNS TABLE(title TEXT, category TEXT, distance FLOAT8, advice TEXT)
LANGUAGE sql STABLE AS $$
  SELECT s.title, s.category, s.embedding <=> c.embedding AS distance, s.advice
  FROM scamshield.scam_storylines s,
       (SELECT embedding FROM scamshield.case_snapshots WHERE household_id = p_hh ORDER BY ts DESC LIMIT 1) c
  WHERE (p_category IS NULL OR s.category = p_category)
    AND (s.embedding <=> c.embedding) <= p_max_distance
  ORDER BY s.embedding <=> c.embedding LIMIT p_limit $$;
