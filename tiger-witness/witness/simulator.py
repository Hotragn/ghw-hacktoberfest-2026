"""SIMULATED users, 13 months of life memory, mandates, ToolTruth-style tool feed, scam storylines, and a 14-day
replay of agent requests.  python -m witness.simulator --reset
No real accounts, no real messages, no real payments. Every row carries simulated=true or lives in a demo table."""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool, text_embedding, vec_literal  # noqa: E402
from witness import agent  # noqa: E402
from tigerprod import hash_password, setup_logging  # noqa: E402

log = logging.getLogger("sim")
R = random.Random(15)
NOW = datetime.now(timezone.utc).replace(microsecond=0)

USERS = [("u-maya", "Maya (demo)", "sms"), ("u-dev", "Dev (demo)", "whatsapp"), ("u-grace", "Grace, 74 (demo)", "imessage")]
TOOLS = [  # (tool_id, capability, publisher, reputation, drift, irreversible)
    ("billpay.plaid-sim", "payments", "Plaid (sim)", 0.96, False, True),
    ("checkout.ap2-sim", "payments", "AP2 reference (sim)", 0.93, False, True),
    ("reserve.opentable-sim", "booking", "OpenTable (sim)", 0.91, False, True),
    ("subs.cancel-sim", "subscriptions", "Rocket Money-like (sim)", 0.88, False, True),
    ("marketplace.reply-sim", "marketplace", "community MCP (sim)", 0.84, False, False),
    ("subs.cancel-cheap-sim", "subscriptions", "unknown publisher (sim)", 0.41, True, True),
]
STORYLINES = [
    ("irs-giftcard", "IRS / warrant gift-card scam", True, "urgent irs warrant arrest pay now in gift cards do not tell anyone"),
    ("grandchild", "Grandchild emergency", True, "grandma its me i am in jail need bail money wire it urgent do not tell mom"),
    ("tech-refund", "Tech-support refund", True, "your account was suspended refund overpaid verify your account remote access buy gift cards"),
    ("pig-butcher", "Crypto investment romance", True, "my uncle trading platform crypto bitcoin guaranteed profit deposit more to withdraw"),
    ("toll-smish", "Unpaid toll smishing", True, "final notice unpaid toll balance pay today avoid penalty click link"),
    ("benign-bill", "Normal bill reminder", False, "your monthly statement is ready autopay scheduled amount due on the due date"),
    ("benign-friend", "Friend making plans", False, "dinner saturday book a table at the italian place for four"),
]


def life(user: str, rich: float):
    rows, start = [], NOW - timedelta(days=395)
    for mo in range(13):
        d0 = start + timedelta(days=30 * mo)
        season = 1.35 if (d0.month in (7, 8, 1, 2)) else 1.0
        rows += [(d0 + timedelta(days=1), "bill", "Rent - Elm St Apts", "housing", round(1850 * rich, 2)),
                 (d0 + timedelta(days=12), "bill", "ConEd", "utilities", round(R.uniform(85, 120) * season, 2)),
                 (d0 + timedelta(days=15), "bill", "Verizon", "phone", 85.00),
                 (d0 + timedelta(days=3), "subscription", "Netflix", "entertainment", 15.49 if mo < 5 else 17.99 if mo < 10 else 22.99),
                 (d0 + timedelta(days=7), "subscription", "Spotify", "entertainment", 11.99),
                 (d0 + timedelta(days=9), "subscription", "Equinox", "fitness", 64.00)]
        for w in range(4):
            rows.append((d0 + timedelta(days=7 * w + 2), "txn", "Whole Foods", "groceries", round(R.uniform(60, 130) * rich, 2)))
            if R.random() < 0.6:
                rows.append((d0 + timedelta(days=7 * w + 5), "txn", "Uber", "transport", round(R.uniform(12, 38), 2)))
            rows.append((d0 + timedelta(days=7 * w + 4), "usage", "Spotify", "entertainment", None))
            if mo < 9:
                rows.append((d0 + timedelta(days=7 * w + 6), "usage", "Equinox", "fitness", None))
            rows.append((d0 + timedelta(days=7 * w + 1), "usage", "Netflix", "entertainment", None))
    return [(ts, user, k, m, c, a) for ts, k, m, c, a in rows if ts < NOW]


async def refresh(c, view: str, tries: int = 10):
    """Refresh a cagg, retrying while the background policy job holds the refresh lock."""
    import asyncpg
    for i in range(tries):
        try:
            return await c.execute(f"CALL refresh_continuous_aggregate('witness.{view}', NULL, NULL)")
        except asyncpg.exceptions.LockNotAvailableError:
            await asyncio.sleep(0.5 * (i + 1))
    raise RuntimeError(f"could not refresh {view}")


async def seed(pool, reset: bool):
    async with pool.acquire() as c:
        if reset:
            await c.execute("ALTER TABLE receipts DISABLE TRIGGER receipts_no_mutation")
            await c.execute("TRUNCATE sessions, accounts, approvals, receipts, actions, inbound, memories, mandates, tools, scam_storylines, life_events, users CASCADE")
            await c.execute("ALTER TABLE receipts ENABLE TRIGGER receipts_no_mutation")
        await c.executemany("INSERT INTO users (user_id, display_name, home_channel) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", USERS)
        demo_pw = os.environ.get("WITNESS_DEMO_PASSWORD", "witness-demo-pass")
        await c.executemany("INSERT INTO accounts (user_id,email,pw_hash) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                            [(u, u[2:] + "@demo.witness.local", hash_password(demo_pw)) for u, _, _ in USERS])
        await c.executemany("INSERT INTO tools VALUES ($1,$2,$3,$4,$5,$6, now()) ON CONFLICT (tool_id) DO UPDATE SET reputation=EXCLUDED.reputation", TOOLS)
        await c.executemany("INSERT INTO scam_storylines VALUES ($1,$2,$3,$4,$5::vector) ON CONFLICT DO NOTHING",
                            [(i, t, s, x, vec_literal(text_embedding(x))) for i, t, s, x in STORYLINES])
        for (uid, _, _), rich in zip(USERS, (1.0, 0.8, 0.6)):
            rows = life(uid, rich)
            await c.copy_records_to_table("life_events", records=rows, schema_name="witness",
                                          columns=["ts", "user_id", "kind", "merchant", "category", "amount"])
            # address + bill memories (data-classed) for recall
            addr_id = await c.fetchval("""INSERT INTO life_events (ts,user_id,kind,detail) VALUES ($1,$2,'profile',
                '{"field":"home_address","value":"(demo) 12 Elm St Apt 4B"}') RETURNING event_id""", NOW - timedelta(days=390), uid)
            mem = [(uid, NOW - timedelta(days=390), "profile", "address", "home address 12 Elm St Apt 4B (demo)", addr_id)]
            for r in await c.fetch("""SELECT DISTINCT ON (merchant) event_id, ts, kind, merchant, category, amount FROM life_events
                    WHERE user_id=$1 AND kind IN ('bill','subscription') ORDER BY merchant, ts DESC""", uid):
                desc = {"utilities": "electric power utility", "phone": "mobile phone wireless", "housing": "rent apartment landlord",
                        "entertainment": "streaming tv music", "fitness": "gym membership"}.get(r["category"], r["category"])
                mem.append((uid, r["ts"], r["kind"], "financial",
                            f"{r['merchant']} {r['kind']} {desc} ${r['amount']}", r["event_id"]))
            await c.executemany("""INSERT INTO memories (user_id,ts,kind,data_class,text,source_event_id,embedding)
                                   VALUES ($1,$2,$3,$4,$5,$6,$7::vector)""",
                                [m + (vec_literal(text_embedding(m[4])),) for m in mem])
        M = NOW - timedelta(days=60)
        mandates = [
            ("m-maya-bills", "u-maya", "standing", "pay_bill", "*", 300, 700, [], None, 10, None, "Pay recurring bills up to $300"),
            ("m-maya-groceries", "u-maya", "standing", "purchase", "whole foods", 150, 500, [], None, 2, None, "Weekly groceries"),
            ("m-maya-market", "u-maya", "standing", "reply", "marketplace:*", None, None, [], None, 4, None, "Answer Marketplace buyers (no personal info)"),
            ("m-maya-subs", "u-maya", "standing", "cancel_subscription", "*", None, None, [], None, 2, None, "Cancel subscriptions I ask about"),
            ("m-maya-dinner", "u-maya", "one_time", "book", "lucia*", 120, None, [], 1, None, NOW + timedelta(days=3), "Book Fri dinner at Lucia's"),
            ("m-dev-bills", "u-dev", "standing", "pay_bill", "*", 200, 400, [], None, 5, None, "Pay bills up to $200"),
            ("m-grace-bills", "u-grace", "standing", "pay_bill", "*", 150, 300, [], None, 3, None, "Pay utility bills (daughter co-signed)"),
        ]
        await c.executemany("""INSERT INTO mandates (mandate_id,user_id,kind,action,counterparty,max_amount,monthly_cap,disclose,
            uses_left,daily_action_budget,expires_at,note,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT DO NOTHING""", [m + (M,) for m in mandates])
        for v in ("spend_daily", "spend_monthly"):
            await refresh(c, v)


async def scenarios(pool):
    """14 days of realistic requests, replayed through the real agent (timestamps in the past)."""
    reqs = [
        (13, "u-maya", "pay my verizon bill"), (12, "u-maya", "order groceries from whole foods for $96"),
        (11, "u-maya", "reply to buyer sam yes the lamp is still available"),
        (10, "u-maya", "pay the electric bill"),                              # resolved via pgvector recall -> ConEd
        (9, "u-maya", "pay my coned bill $412"),                             # 3x her baseline -> needs approval
        (8, "u-maya", "cancel equinox"),                                     # idle subscription
        (6, "u-maya", "reply to buyer jo sure, pick up at my place tonight, here is my address"),  # Muse incident
        (5, "u-maya", "book a table for two at lucia's for $90"),
        (5, "u-maya", "book a table for four at lucia's for $110"),          # one-time mandate already used
        (4, "u-maya", "order groceries from whole foods for $210"),          # over per-action limit
        (3, "u-dev", "pay my verizon bill"), (3, "u-dev", "pay my rent bill"),  # rent > $200 mandate
        (2, "u-maya", "pay my water bill $60"),                              # no evidence -> assumption
    ]
    for i in range(1, 8):  # consent drift: marketplace replies ramp up 1 -> 7 per day
        for k in range(i):
            reqs.append((8 - i, "u-maya", f"reply to buyer b{i}{k} is it still available? yes"))
    for days, uid, text in sorted(reqs, key=lambda r: -r[0]):
        at = NOW - timedelta(days=days, hours=R.randint(0, 6), minutes=R.randint(0, 59))
        r = await agent.handle(pool, uid, text, at=at)
        log.info("%-8s %-60s -> %s", uid, text[:60], r["decision"])
    inbound = [
        (2, "u-grace", "sms", "+1-202-555-0199", "URGENT this is the IRS. A warrant is issued. Pay $900 in gift cards to IRS agent today, do not tell anyone"),
        (1, "u-grace", "imessage", "Unknown", "Grandma its me, I am in jail and need bail. Pay $2500 wire to my lawyer, urgent, do not tell mom"),
        (1, "u-grace", "sms", "ConEd Alerts", "Your monthly statement is ready. Pay my coned bill when due."),
    ]
    for days, uid, ch, sender, body in inbound:
        r = await agent.handle_inbound(pool, uid, ch, sender, body, at=NOW - timedelta(days=days, hours=2))
        log.info("%-8s inbound %-45s -> %s", uid, body[:45], r["decision"])
    async with pool.acquire() as c:
        await refresh(c, "actions_hourly")


async def run(reset: bool = True, with_scenarios: bool = True):
    pool = await make_pool("witness")
    try:
        await seed(pool, reset)
        if with_scenarios:
            await scenarios(pool)
    finally:
        await pool.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-scenarios", action="store_true")
    a = ap.parse_args()
    setup_logging()
    if not a.reset:
        raise SystemExit("seeding is destructive-by-design for the demo dataset: pass --reset")
    await run(True, not a.no_scenarios)

if __name__ == "__main__":
    asyncio.run(main())
