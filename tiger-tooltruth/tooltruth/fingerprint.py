"""Behaviour fingerprint job: one 16-dim vector per tool per window, stored in tooltruth.tool_behavior.
Also seeds 'known-bad' reference fingerprints (exfil, endpoint hijack, degraded/compromised).

  python -m tooltruth.fingerprint --windows 24 --window-hours 1   # backfill fingerprints
  python -m tooltruth.fingerprint --loop 300                      # every 5 minutes
"""
from __future__ import annotations
import argparse, asyncio, logging, math, os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool, vec_literal  # noqa: E402

log = logging.getLogger("fingerprint")
NS_LABELS = {"github": 1, "slack": 2, "fs": 3, "web": 4, "db": 5, "payments": 6, "calendar": 7,
             "email": 8, "jira": 9, "docs": 10, "crm": 11}
FEATURE_SQL = """
WITH cur AS (
  SELECT tool, count(*) n,
         avg((status <> 'ok')::int) err,
         avg((status = 'timeout')::int) tmo,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) p50,
         percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) p95,
         avg(bytes_out) bytes, max(bytes_out) bytes_max,
         avg(cardinality(destinations)) ndest,
         count(DISTINCT version) nver, max(version) ver,
         sum(cost_usd)/NULLIF(sum((status='ok')::int),0) cps,
         count(DISTINCT org) orgs
  FROM tool_calls WHERE ts > $1 AND ts <= $2 GROUP BY tool),
newd AS (
  SELECT c.tool, count(DISTINCT c.dest) new_dests, coalesce(sum(c.bytes),0) new_bytes
  FROM call_destinations c
  WHERE c.ts > $1 AND c.ts <= $2
    AND NOT EXISTS (SELECT 1 FROM call_destinations b WHERE b.tool=c.tool AND b.dest=c.dest
                    AND b.ts > $1 - interval '7 days' AND b.ts <= $1 - interval '12 hours')
  GROUP BY c.tool),
alld AS (SELECT tool, count(DISTINCT dest) dests FROM call_destinations WHERE ts > $1 AND ts <= $2 GROUP BY tool)
SELECT cur.*, coalesce(newd.new_dests,0) new_dests, coalesce(newd.new_bytes,0) new_bytes, alld.dests,
       t.namespace
FROM cur JOIN tools t USING (tool) LEFT JOIN newd USING (tool) LEFT JOIN alld USING (tool)
"""


def features(r) -> list[float]:
    lg = lambda x: math.log10(1 + max(0.0, float(x or 0)))  # noqa: E731
    v = [
        float(r["err"]) * 3, float(r["tmo"]) * 5,
        lg(r["p50"]) / 4, lg(r["p95"]) / 4,
        lg(r["bytes"]) / 6, lg(r["bytes_max"]) / 7,
        float(r["ndest"] or 0) / 2, float(r["dests"] or 0) / 3,
        min(1.0, float(r["new_dests"]) / 1.0), lg(r["new_bytes"]) / 8,
        (float(r["nver"]) - 1), lg((r["cps"] or 0) * 1e6) / 5,
        min(1.0, float(r["orgs"]) / 6), 0.5,  # constant bias dim keeps cosine stable for quiet tools
        float(r["new_dests"] > 0 and float(r["bytes"]) > 50000), float(r["new_dests"] > 0 and r["nver"] > 1),
    ]
    return v


KNOWN_BAD = [
    # (note, feature vector) - archetypes from incident write-ups (simulated)
    ("exfil: new host + huge payloads after update",
     [0.03, 0.0, 0.6, 0.75, 0.85, 0.85, 1.0, 0.67, 1.0, 0.8, 1.0, 0.6, 1.0, 0.5, 1.0, 1.0]),
    ("endpoint hijack: all traffic moved to unknown host",
     [0.03, 0.0, 0.6, 0.75, 0.6, 0.65, 0.5, 0.67, 1.0, 0.6, 1.0, 0.6, 1.0, 0.5, 0.0, 1.0]),
    ("compromised/degraded: error+latency spike after update",
     [0.6, 0.3, 0.85, 0.95, 0.6, 0.65, 0.5, 0.33, 0.0, 0.0, 1.0, 0.7, 1.0, 0.5, 0.0, 0.0]),
]


async def seed_known_bad(pool):
    async with pool.acquire() as c:
        if await c.fetchval("SELECT count(*) FROM tool_behavior WHERE known_bad"):
            return
        for note, vec in KNOWN_BAD:
            await c.execute("""INSERT INTO tool_behavior(tool, namespace, ns_label, labels, window_end, known_bad, note, embedding)
                               VALUES($1,'reference',0,'{0}',now(),true,$2,$3::vector)""",
                            f"ref:{note.split(':')[0]}", note, vec_literal(vec))
        log.info("seeded %d known-bad references", len(KNOWN_BAD))


async def fingerprint_window(pool, start: datetime, end: datetime) -> int:
    async with pool.acquire() as c:
        rows = await c.fetch(FEATURE_SQL, start, end)
        recs = []
        for r in rows:
            ns = r["namespace"]
            recs.append((r["tool"], ns, NS_LABELS.get(ns, 99), [NS_LABELS.get(ns, 99)], end, r["ver"],
                         vec_literal(features(r))))
        await c.executemany("""INSERT INTO tool_behavior(tool, namespace, ns_label, labels, window_end, version, embedding)
                               VALUES($1,$2,$3,$4,$5,$6,$7::vector)""", recs)
    return len(recs)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=1)
    ap.add_argument("--window-hours", type=float, default=1)
    ap.add_argument("--loop", type=int, default=0, help="seconds between runs (0 = once)")
    a = ap.parse_args()
    pool = await make_pool("tooltruth")
    await seed_known_bad(pool)
    while True:
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        w = timedelta(hours=a.window_hours)
        total = 0
        for i in range(a.windows - 1, -1, -1):
            total += await fingerprint_window(pool, end - w * (i + 1), end - w * i)
        log.info("wrote %d fingerprints", total)
        if not a.loop:
            break
        a.windows = 1
        await asyncio.sleep(a.loop)
    await pool.close()

if __name__ == "__main__":
    from tigerprod import setup_logging
    setup_logging(); asyncio.run(main())
