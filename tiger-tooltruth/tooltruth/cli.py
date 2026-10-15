"""tooltruth CLI.

  python -m tooltruth.cli diff <tool> [--recent 6h] [--baseline 3d]
  python -m tooltruth.cli suspects [--ns web] [--max-distance 0.15]
  python -m tooltruth.cli health
"""
from __future__ import annotations
import argparse, asyncio, os, re, sys
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool  # noqa: E402

DIFF_SQL = """
WITH w AS (
  SELECT CASE WHEN ts > now() - $2::interval THEN 'recent' ELSE 'baseline' END AS win, *
  FROM tool_calls WHERE tool = $1 AND ts > now() - $2::interval - $3::interval)
SELECT win, count(*) calls, array_agg(DISTINCT version) versions,
       round(avg((status<>'ok')::int)::numeric, 4) error_rate,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 1) p95_ms,
       round(avg(bytes_out)) avg_bytes,
       round((sum(cost_usd)/NULLIF(sum((status='ok')::int),0))::numeric, 6) cost_per_success,
       (SELECT array_agg(DISTINCT d) FROM w w2, unnest(w2.destinations) d WHERE w2.win = w.win) dests
FROM w GROUP BY win ORDER BY win DESC
"""
FP_SQL = """
SELECT (SELECT embedding FROM tool_behavior WHERE tool=$1 AND NOT known_bad ORDER BY window_end DESC LIMIT 1)
   <=> (SELECT embedding FROM tool_behavior WHERE tool=$1 AND NOT known_bad AND window_end < now() - $2::interval
        ORDER BY window_end DESC LIMIT 1) AS drift,
       (SELECT min(b.embedding <=> t.embedding) FROM tool_behavior b, tool_behavior t
        WHERE b.known_bad AND t.tool = $1 AND NOT t.known_bad AND t.window_end > now() - $2::interval) AS dist_to_bad
"""


def iv(s: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 30m, 6h, 3d")
    n, u = int(m[1]), m[2]
    return timedelta(minutes=n) if u == "m" else timedelta(hours=n) if u == "h" else timedelta(days=n)


def table(rows, cols):
    if not rows:
        print("(no rows)"); return
    data = [[str(r[c]) for c in cols] for r in rows]
    w = [max(len(c), *(len(d[i]) for d in data)) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    for d in data:
        print("  ".join(x.ljust(w[i]) for i, x in enumerate(d)))


async def diff(tool, recent, baseline):
    pool = await make_pool("tooltruth")
    async with pool.acquire() as c:
        rows = await c.fetch(DIFF_SQL, tool, recent, baseline)
        fp = await c.fetchrow(FP_SQL, tool, recent)
    await pool.close()
    if not rows:
        print(f"no calls for {tool}"); return 1
    by = {r["win"]: r for r in rows}
    print(f"\n== tooltruth diff {tool}  (recent {recent} vs prior {baseline}) ==")
    for r in rows:
        print(f"[{r['win']:8}] calls={r['calls']} versions={r['versions']} err={r['error_rate']} "
              f"p95={r['p95_ms']}ms bytes={r['avg_bytes']} $/success={r['cost_per_success']}")
    if "recent" in by and "baseline" in by:
        b, n = set(by["baseline"]["dests"] or []), set(by["recent"]["dests"] or [])
        print("destinations added:  ", sorted(n - b) or "-")
        print("destinations removed:", sorted(b - n) or "-")
        print("version change:      ", sorted(set(by["baseline"]["versions"])), "->", sorted(set(by["recent"]["versions"])))
        rb, rn = by["baseline"], by["recent"]
        for k in ("error_rate", "p95_ms", "avg_bytes", "cost_per_success"):
            if rb[k] and rn[k] is not None:
                print(f"{k:20} x{float(rn[k]) / float(rb[k]):.2f}")
    if fp and fp["drift"] is not None:
        print(f"fingerprint drift (cosine): {fp['drift']:.3f}   nearest known-bad distance: {fp['dist_to_bad']:.3f}")
    verdict = "SUSPICIOUS" if fp and fp["dist_to_bad"] is not None and fp["dist_to_bad"] < 0.05 else "ok"
    print("verdict:", verdict)
    return 0


async def suspects(ns, maxd, since):
    pool = await make_pool("tooltruth")
    rows = await pool.fetch("SELECT * FROM behaving_like_known_bad($1, $2, $3)", since, ns, maxd)
    await pool.close()
    table(rows, ["tool", "namespace", "version", "nearest_bad", "distance"])


async def health(since):
    pool = await make_pool("tooltruth")
    rows = await pool.fetch("SELECT * FROM tool_health($1) ORDER BY error_rate DESC LIMIT 15", since)
    await pool.close()
    table(rows, ["tool", "calls", "error_rate", "p95_latency_ms", "cost_per_success"])


def main():
    ap = argparse.ArgumentParser(prog="tooltruth")
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("diff"); d.add_argument("tool"); d.add_argument("--recent", type=iv, default="6h"); d.add_argument("--baseline", type=iv, default="3d")
    s = sp.add_parser("suspects"); s.add_argument("--ns"); s.add_argument("--max-distance", type=float, default=0.05); s.add_argument("--since", type=iv, default="24h")
    h = sp.add_parser("health"); h.add_argument("--since", type=iv, default="24h")
    a = ap.parse_args()
    if a.cmd == "diff":
        sys.exit(asyncio.run(diff(a.tool, a.recent, a.baseline)))
    if a.cmd == "suspects":
        asyncio.run(suspects(a.ns, a.max_distance, a.since))
    if a.cmd == "health":
        asyncio.run(health(a.since))

if __name__ == "__main__":
    main()
