"""Risk detector. For each household with active consent:
  1. pull 7-day features from continuous aggregates (risk_features)
  2. check fake profit screens vs real Coinbase BTC (fake_profit_screens)
  3. write a plain-language narrative, embed it, and find the nearest known scam storyline (pgvector)
  4. if risk >= threshold: record an alert. Delivery is SIMULATED (logged), never a real message,
     and is suppressed if the 'alerts' consent scope is missing or monitoring is paused.

  python -m scamshield.detector            # once
  python -m scamshield.detector --loop 300
"""
from __future__ import annotations
import argparse, asyncio, json, logging, os, sys
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool, text_embedding, vec_literal  # noqa: E402

log = logging.getLogger("detector")
THRESHOLD = 0.5


def score(f, fakes) -> tuple[float, list[str], str]:
    reasons, parts, s = [], [], 0.0
    if f["night_call_minutes"] > 120:
        s += 0.2; reasons.append(f"{f['night_call_minutes']:.0f} min of late-night calls")
        parts.append("long late night phone calls every night from overseas unknown caller")
    if f["intl_calls"] >= 5:
        s += 0.1; reasons.append(f"{f['intl_calls']} international calls"); parts.append("repeated calls from international numbers")
    if f["night_door_events"] >= 1:
        s += 0.1; reasons.append("door opened at night"); parts.append("a courier comes to the door late at night")
    if f["sleep_disruption"] > 0.35:
        s += 0.1; reasons.append(f"sleep disruption {f['sleep_disruption']:.2f}"); parts.append("sleep disrupted")
    if f["kiosk_visits"] >= 1 or f["kiosk_usd"] > 0:
        s += 0.25; reasons.append(f"{f['kiosk_visits']} crypto-kiosk visits, ${f['kiosk_usd']:,.0f} deposited")
        parts.append("deposits cash at a bitcoin kiosk again and again")
    if f["gift_card_usd"] > 300:
        s += 0.25; reasons.append(f"${f['gift_card_usd']:,.0f} in gift cards"); parts.append("caller says computer hacked and refund overpaid, takes remote control, asks to buy gift cards and keeps them on the phone for hours")
    if f["wire_usd"] > 1000:
        s += 0.2; reasons.append(f"${f['wire_usd']:,.0f} wired abroad"); parts.append("wire transfer to overseas refund account")
    if fakes:
        gap = max(x["gap_pct"] for x in fakes)
        s += 0.3; reasons.append(f"investment app shows BTC {gap:.0f}% above the real Coinbase price ({len(fakes)} screens)")
        parts.append("a crypto investment app showing huge profits above the market price; balance keeps growing")
    narrative = ". ".join(parts) or "regular daytime calls with family, groceries and pharmacy, normal sleep"
    return min(1.0, s), reasons, narrative


async def run_once(pool):
    async with pool.acquire() as c:
        hhs = await c.fetch("SELECT * FROM households ORDER BY household_id")
        for hh in hhs:
            hid = hh["household_id"]
            if hh["consent_status"] != "active":
                log.info("%s: consent %s -> not analysed", hid, hh["consent_status"]); continue
            f = await c.fetchrow("SELECT * FROM risk_features($1, $2)", hid, timedelta(days=7))
            fakes = await c.fetch("SELECT * FROM fake_profit_screens($1) WHERE household_id=$2", timedelta(days=7), hid)
            s, reasons, narrative = score(f, fakes)
            await c.execute("INSERT INTO case_snapshots(household_id, narrative, embedding) VALUES($1,$2,$3::vector)",
                            hid, narrative, vec_literal(text_embedding(narrative)))
            match = await c.fetchrow("SELECT * FROM similar_storylines($1, NULL, 0.95, 1)", hid)
            log.info("%s risk=%.2f match=%s", hid, s, match and (match["title"], round(match["distance"], 3)))
            if s < THRESHOLD or (match and match["category"] == "benign"):
                continue
            allowed = await c.fetchval("SELECT consent_allows($1,'alerts')", hid)
            paused = hh["paused_until"] is not None and await c.fetchval("SELECT $1 > now()", hh["paused_until"])
            delivery = "suppressed_paused" if paused else ("simulated_to_trusted_contact" if allowed else "suppressed_no_consent")
            msg = (f"[SIMULATED - not sent] Hi {hh['trusted_contact']}, {hh['display_name']} agreed to share early warnings with you. "
                   f"Pattern resembles '{match['title'] if match else 'unknown'}': " + "; ".join(reasons) +
                   f". Suggested: {match['advice'] if match else 'check in kindly'}. Please call them; do not confront.")
            await c.execute("""INSERT INTO alerts(household_id, risk_score, reasons, storyline, distance, delivery, message)
                               VALUES($1,$2,$3,$4,$5,$6,$7)""", hid, s, json.dumps(reasons),
                            match and match["title"], match and match["distance"], delivery, msg)
            log.warning("ALERT %s (%s): %s", hid, delivery, msg)


async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", type=int, default=0); a = ap.parse_args()
    pool = await make_pool("scamshield")
    while True:
        await run_once(pool)
        if not a.loop:
            break
        await asyncio.sleep(a.loop)
    await pool.close()

if __name__ == "__main__":
    from tigerprod import setup_logging
    setup_logging(); asyncio.run(main())
