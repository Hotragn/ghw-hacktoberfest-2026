"""SIMULATED smart-home + finance dataset for 5 consenting households.
  hh-001 Rosa   : pig-butchering crypto scam over ~10 days (night intl calls, kiosk visits, fake profit app)
  hh-002 Walter : tech-support/gift-card scam in the last 3 days
  hh-003 Margaret, hh-004 Ernest : normal routines
  hh-005 Helen  : consent PENDING -> nothing is ingested for her (consent gate demo)
BTC values use live Coinbase BTC-USD (current price for backfill, live ticks for --live).

  python -m scamshield.simulator --seed-only
  python -m scamshield.simulator --backfill-days 14
  python -m scamshield.simulator --live --seconds 0
"""
from __future__ import annotations
import argparse, asyncio, json, logging, os, random, sys, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import BatchWriter, coinbase_ticker, make_pool, text_embedding, vec_literal  # noqa: E402
from scamshield.storylines import CATEGORY_LABELS, STORYLINES  # noqa: E402

log = logging.getLogger("sim")
TZ = ZoneInfo("America/New_York")
ALL_SCOPES = ["calls", "door", "sleep", "location", "transactions", "screens", "alerts"]
HOUSEHOLDS = [
    ("hh-001", "Rosa (sim)", "active", "Daniel (son, sim)", "pig"),
    ("hh-002", "Walter (sim)", "active", "Priya (daughter, sim)", "tech"),
    ("hh-003", "Margaret (sim)", "active", "Sam (neighbor, sim)", "normal"),
    ("hh-004", "Ernest (sim)", "active", "Lena (niece, sim)", "normal"),
    ("hh-005", "Helen (sim)", "pending", "Joe (son, sim)", "normal"),
]
SCOPE_FOR_KIND = {"call": "calls", "door": "door", "sleep": "sleep", "location": "location"}


async def seed(pool):
    async with pool.acquire() as c:
        for hid, name, status, contact, _ in HOUSEHOLDS:
            new = await c.fetchval("""INSERT INTO households(household_id, display_name, consent_status, consent_scopes,
                                 trusted_contact, consented_by, consented_at)
                               VALUES($1,$2,$3,$4,$5,$6,CASE WHEN $3='active' THEN now() END)
                               ON CONFLICT (household_id) DO NOTHING RETURNING household_id""",
                            hid, name, status, ALL_SCOPES if status == "active" else [], contact, name)
            if new and status == "active":
                await c.execute("INSERT INTO consent_log(household_id, actor, action, scopes, note) VALUES($1,$2,'grant',$3,'initial onboarding (simulated)')",
                                hid, name, ALL_SCOPES)
            for kind, model, room in [("phone_hub", "SimLine 2", "kitchen"), ("door_sensor", "SimDoor", "front door"),
                                      ("sleep_mat", "SimSleep", "bedroom"), ("phone_gps", "SimGPS", "mobile")]:
                await c.execute("""INSERT INTO devices VALUES($1,$2,$3,$4,$5,now()-interval '60 days','1.4.2')
                                   ON CONFLICT DO NOTHING""", f"{hid}-{kind}", hid, kind, model, room)
        for title, cat, story, advice in STORYLINES:
            await c.execute("""INSERT INTO scam_storylines(title, category, cat_label, labels, story, advice, embedding)
                               VALUES($1,$2,$3,$4,$5,$6,$7::vector) ON CONFLICT (title) DO NOTHING""",
                            title, cat, CATEGORY_LABELS[cat], [CATEGORY_LABELS[cat]], story, advice,
                            vec_literal(text_embedding(title + ". " + story)))
    log.info("seeded households, devices, storylines")


async def current_btc() -> float:
    if os.environ.get("SCAMSHIELD_OFFLINE_BTC"):  # tests / air-gapped runs
        return float(os.environ["SCAMSHIELD_OFFLINE_BTC"])
    async def first():
        async for t in coinbase_ticker(["BTC-USD"]):
            return t["price"]
    try:
        return await asyncio.wait_for(first(), 15)
    except asyncio.TimeoutError:
        log.warning("coinbase timeout, using 60000"); return 60000.0


def day_events(hid: str, profile: str, day: datetime, days_ago: int, btc: float, rnd: random.Random):
    """Yield ('signal'|'tx'|'claim', row) for one local day."""
    def at(h, m=0):
        return (day + timedelta(hours=h, minutes=m)).astimezone(timezone.utc)

    def sig(ts, dev, kind, value, meta):
        lh = ts.astimezone(TZ).hour
        return ("signal", (ts, hid, f"{hid}-{dev}", kind, value, lh, json.dumps(meta)))

    # baseline routine
    for _ in range(rnd.randint(2, 5)):
        yield sig(at(rnd.randint(9, 19), rnd.randint(0, 59)), "phone_hub", "call", rnd.uniform(2, 20), {"caller": "known", "intl": False})
    for _ in range(rnd.randint(2, 4)):
        yield sig(at(rnd.randint(8, 20), rnd.randint(0, 59)), "door_sensor", "door", rnd.uniform(5, 60), {})
    yield sig(at(7), "sleep_mat", "sleep", rnd.uniform(0.05, 0.2), {})
    if rnd.random() < 0.6:
        yield ("tx", (at(rnd.randint(10, 17)), hid, rnd.choice(["groceries", "pharmacy", "utility"]), rnd.uniform(15, 140), None, None, "local merchant"))
        yield sig(at(rnd.randint(10, 17)), "phone_gps", "location", rnd.uniform(15, 50), {"place": "grocery"})

    if profile == "pig" and days_ago <= 10:
        intensity = (11 - days_ago) / 10
        for _ in range(1 + int(3 * intensity)):
            yield sig(at(rnd.choice([22, 23, 0 + 24, 1 + 24]), rnd.randint(0, 59)), "phone_hub", "call",
                      rnd.uniform(30, 120), {"caller": "unknown", "intl": True})
        yield sig(at(7), "sleep_mat", "sleep", min(1, 0.3 + 0.6 * intensity), {})
        if days_ago % 2 == 0:
            usd = rnd.choice([500, 1000, 2000, 3000]) * (1 + intensity)
            yield sig(at(14), "phone_gps", "location", rnd.uniform(10, 25), {"place": "crypto_kiosk"})
            yield ("tx", (at(14, 20), hid, "crypto_kiosk", usd, usd / btc, btc, "BTC kiosk -> unknown wallet"))
        for h in (20, 23):
            yield ("claim", (at(h), hid, "GoldenHarbor Pro", btc * rnd.uniform(1.18, 1.42),
                             12000 * (1 + 2 * intensity), 35 + 140 * intensity))
    if profile == "tech" and days_ago <= 3:
        for _ in range(2):
            yield sig(at(rnd.randint(10, 16)), "phone_hub", "call", rnd.uniform(60, 180), {"caller": "unknown", "intl": True})
        yield sig(at(23, rnd.randint(0, 59)), "door_sensor", "door", rnd.uniform(60, 240), {"note": "courier"})
        yield ("tx", (at(15), hid, "gift_card", rnd.choice([500, 800, 1000]), None, None, "pharmacy gift cards"))
        if days_ago <= 1:
            yield ("tx", (at(11), hid, "wire", 4800.0, None, None, "overseas 'refund' account"))
        yield sig(at(7), "sleep_mat", "sleep", rnd.uniform(0.5, 0.8), {})


SIG_COLS = ["ts", "household_id", "device_id", "kind", "value", "local_hour", "meta"]
TX_COLS = ["ts", "household_id", "kind", "amount_usd", "btc_amount", "btc_usd", "counterparty"]
CLAIM_COLS = ["ts", "household_id", "app_name", "claimed_btc_usd", "claimed_balance_usd", "claimed_return_pct"]


async def refresh_cagg(c, view: str, tries: int = 10):
    """Refresh a cagg, retrying while a background policy job holds the refresh lock."""
    import asyncpg
    for i in range(tries):
        try:
            return await c.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
        except asyncpg.exceptions.LockNotAvailableError:
            await asyncio.sleep(0.5 * (i + 1))
    raise RuntimeError(f"could not refresh {view}")


async def backfill(pool, days: int):
    btc = await current_btc()
    log.info("live BTC-USD for valuation: %.2f", btc)
    rnd = random.Random(11)
    sw = BatchWriter(pool, "home_signals", SIG_COLS, "scamshield", 5000)
    tw = BatchWriter(pool, "transactions", TX_COLS, "scamshield", 5000)
    cw = BatchWriter(pool, "profit_claims", CLAIM_COLS, "scamshield", 5000)
    async with pool.acquire() as c:
        allowed = {(h, s): await c.fetchval("SELECT consent_allows($1,$2)", h, s) for h, *_ in HOUSEHOLDS for s in ALL_SCOPES}
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc)
    skipped = 0
    for hid, _, _, _, profile in HOUSEHOLDS:
        for d in range(days, -1, -1):
            for typ, row in day_events(hid, profile, today - timedelta(days=d), d, btc, rnd):
                if row[0] > now:
                    continue
                scope = SCOPE_FOR_KIND.get(row[3]) if typ == "signal" else ("transactions" if typ == "tx" else "screens")
                if not allowed[(hid, scope)]:
                    skipped += 1
                    continue
                await {"signal": sw, "tx": tw, "claim": cw}[typ].add(row)
    for w in (sw, tw, cw):
        await w.flush()
    # one recent real-price tick so fake-profit comparison works offline of --live
    async with pool.acquire() as c:
        await c.execute("INSERT INTO btc_ticks VALUES(now() - interval '%s days', 'BTC-USD', $1)" % (days + 1), btc)
        for v in ("signals_hourly", "tx_daily"):
            await refresh_cagg(c, f"scamshield.{v}")
    log.info("backfill: %d signals, %d tx, %d claims; %d events dropped by consent gate", sw.total, tw.total, cw.total, skipped)


async def live(pool, seconds: int):
    """Stream Coinbase BTC-USD ticks into btc_ticks and emit occasional live household events."""
    bw = BatchWriter(pool, "btc_ticks", ["ts", "product", "price"], "scamshield", 100, 1.0)
    cw = BatchWriter(pool, "profit_claims", CLAIM_COLS, "scamshield", 10, 2.0)
    timers = [asyncio.create_task(bw.run_timer()), asyncio.create_task(cw.run_timer())]
    t0, last_claim, rnd = time.time(), 0.0, random.Random()
    async for t in coinbase_ticker(["BTC-USD"]):
        ts = datetime.now(timezone.utc)
        await bw.add((ts, t["product"], t["price"]))
        if time.time() - last_claim > 20:
            last_claim = time.time()
            async with pool.acquire() as c:
                ok = await c.fetchval("SELECT consent_allows('hh-001','screens')")
            if ok:
                await cw.add((ts, "hh-001", "GoldenHarbor Pro", t["price"] * rnd.uniform(1.2, 1.4), 41000, 160))
            log.info("BTC-USD %.2f  ticks=%d claims=%d", t["price"], bw.total, cw.total)
        if seconds and time.time() - t0 > seconds:
            break
    for x in timers:
        x.cancel()
    await bw.flush(); await cw.flush()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--backfill-days", type=int, default=0)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--seconds", type=int, default=0)
    a = ap.parse_args()
    pool = await make_pool("scamshield")
    await seed(pool)
    if a.backfill_days:
        await backfill(pool, a.backfill_days)
    if a.live:
        await live(pool, a.seconds)
    await pool.close()

if __name__ == "__main__":
    from tigerprod import setup_logging
    setup_logging(); asyncio.run(main())
