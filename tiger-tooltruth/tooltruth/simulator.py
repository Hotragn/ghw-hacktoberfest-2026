"""Simulated agent fleet calling ~50 simulated MCP tools across orgs.
Scenarios baked in (all SIMULATED, no real tools are called):
  * drift      - tool slowly degrades (latency / errors) after a version bump
  * malicious  - tool update starts sending data to an extra exfil host with large payloads
  * swap       - tool's endpoint silently swapped to a new host
Costs = LLM tokens priced from live OpenRouter + on-chain fee for payments.* tools valued at live ETH-USD.

  python -m tooltruth.simulator --backfill-hours 48            # history (fast, uses COPY)
  python -m tooltruth.simulator --live --rate 20               # real-time stream + live prices
"""
from __future__ import annotations
import argparse, asyncio, logging, math, os, random, sys, time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import BatchWriter, make_pool  # noqa: E402
from tooltruth.pricing import DEFAULT_MODELS, PriceBook, coinbase_loop, fetch_openrouter, openrouter_loop  # noqa: E402

log = logging.getLogger("sim")
NAMESPACES = {
    "github": ["create_issue", "list_prs", "get_file", "search_code", "comment", "merge_pr"],
    "slack": ["post_message", "list_channels", "search", "upload_file", "react"],
    "fs": ["read_file", "write_file", "list_dir", "grep", "stat"],
    "web": ["fetch", "search", "screenshot", "scrape", "summarize_url"],
    "db": ["query", "schema", "explain", "export_csv"],
    "payments": ["quote", "transfer", "balance", "refund"],
    "calendar": ["list_events", "create_event", "free_busy"],
    "email": ["send", "search", "read", "draft"],
    "jira": ["create_ticket", "transition", "search", "comment"],
    "docs": ["create", "append", "search", "export_pdf"],
    "crm": ["lookup", "update_contact", "log_call"],
}
ORGS = ["acme", "globex", "initech", "umbrella", "hooli", "piedpiper"]
EXFIL_HOSTS = ["paste-cdn.example-bad.net", "telemetry-sync.example-bad.io"]


@dataclass
class Tool:
    name: str
    ns: str
    base_latency: float
    err: float
    bytes_mu: float
    dests: list[str]
    version: str = "1.0.0"
    scenario: str = "normal"
    flip_at: datetime | None = None
    flipped: bool = field(default=False)

    def maybe_flip(self, now: datetime):
        if self.flip_at and not self.flipped and now >= self.flip_at:
            self.flipped = True
            major, minor, patch = map(int, self.version.split("."))
            self.version = f"{major}.{minor + 1}.0"
            if self.scenario == "malicious":
                self.dests = self.dests + [random.choice(EXFIL_HOSTS)]
                self.bytes_mu += math.log(25)
            elif self.scenario == "swap":
                self.dests = [d.replace("api.", "api-v2.").replace(".com", "-edge.net") for d in self.dests]
            elif self.scenario == "drift":
                self.base_latency *= 4
                self.err = min(0.5, self.err * 8)


def build_tools(now: datetime, seed: int = 7) -> list[Tool]:
    rnd = random.Random(seed)
    tools = []
    for ns, ops in NAMESPACES.items():
        for op in ops:
            tools.append(Tool(f"{ns}.{op}", ns, rnd.uniform(40, 900), rnd.uniform(0.002, 0.03),
                              rnd.uniform(6, 10), [f"api.{ns}.com"]))
    names = {t.name: t for t in tools}
    plan = {"web.summarize_url": "malicious", "docs.export_pdf": "malicious", "crm.lookup": "malicious",
            "slack.upload_file": "swap", "db.export_csv": "swap",
            "jira.search": "drift", "github.search_code": "drift", "calendar.free_busy": "drift"}
    for name, sc in plan.items():
        t = names[name]
        t.scenario, t.flip_at = sc, now - timedelta(hours=rnd.uniform(2, 10))
    return tools


def make_call(t: Tool, now: datetime, book: PriceBook, rnd: random.Random) -> tuple:
    t.maybe_flip(now)
    hour = now.hour
    load = 1 + 0.5 * math.sin((hour - 14) / 24 * 2 * math.pi)
    lat = rnd.lognormvariate(math.log(t.base_latency * load), 0.35)
    r = rnd.random()
    status = "timeout" if r < t.err * 0.2 else ("error" if r < t.err else "ok")
    if status == "timeout":
        lat = max(lat, 30000)
    bytes_out = int(rnd.lognormvariate(t.bytes_mu, 0.6))
    model = rnd.choice(DEFAULT_MODELS)
    tin, tout = rnd.randint(300, 4000), rnd.randint(50, 800)
    cost = book.token_cost(model, tin, tout)
    if t.ns == "payments" and status == "ok":
        eth = book.eth_usd or 2500.0
        cost += rnd.uniform(0.00002, 0.0002) * eth  # simulated L2 gas in ETH -> USD
    agent = f"agent-{rnd.randint(1, 40):02d}"
    org = ORGS[int(agent[-2:]) % len(ORGS)] if rnd.random() < 0.8 else rnd.choice(ORGS)
    return (now, agent, org, t.name, t.version, lat, status, bytes_out, list(t.dests), model, tin, tout, cost)


COLS = ["ts", "agent", "org", "tool", "version", "latency_ms", "status", "bytes_out", "destinations",
        "model", "tokens_in", "tokens_out", "cost_usd"]


async def write_call(row, calls: BatchWriter, dests: BatchWriter):
    await calls.add(row)
    for d in row[8]:
        await dests.add((row[0], row[3], row[2], d, row[7] // max(1, len(row[8]))))


async def register_tools(pool, tools):
    async with pool.acquire() as c:
        await c.executemany("INSERT INTO tools(tool, namespace, publisher) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                            [(t.name, t.ns, f"{t.ns}-mcp-community") for t in tools])


async def backfill(pool, hours: int, per_hour: int, book: PriceBook):
    now = datetime.now(timezone.utc)
    tools = build_tools(now)
    await register_tools(pool, tools)
    rnd = random.Random(42)
    calls = BatchWriter(pool, "tool_calls", COLS, "tooltruth", max_rows=5000)
    dests = BatchWriter(pool, "call_destinations", ["ts", "tool", "org", "dest", "bytes"], "tooltruth", max_rows=5000)
    start = now - timedelta(hours=hours)
    n = hours * per_hour
    for i in range(n):
        ts = start + timedelta(seconds=i * 3600 / per_hour)
        await write_call(make_call(rnd.choice(tools), ts, book, rnd), calls, dests)
    await calls.flush(); await dests.flush()
    log.info("backfilled %d calls / %d destination rows over %dh", calls.total, dests.total, hours)


async def live(pool, rate: float, book: PriceBook, seconds: int):
    now = datetime.now(timezone.utc)
    tools = build_tools(now)
    await register_tools(pool, tools)
    rnd = random.Random()
    calls = BatchWriter(pool, "tool_calls", COLS, "tooltruth", max_rows=200)
    dests = BatchWriter(pool, "call_destinations", ["ts", "tool", "org", "dest", "bytes"], "tooltruth", max_rows=200)
    pw = BatchWriter(pool, "prices", ["ts", "source", "symbol", "price"], "tooltruth", max_rows=100)
    bg = [asyncio.create_task(x) for x in (calls.run_timer(), dests.run_timer(), pw.run_timer(),
                                           openrouter_loop(book, pw), coinbase_loop(book, pw))]
    t0 = time.time()
    while not seconds or time.time() - t0 < seconds:
        await write_call(make_call(rnd.choice(tools), datetime.now(timezone.utc), book, rnd), calls, dests)
        await asyncio.sleep(rnd.expovariate(rate))
        if int(time.time()) % 10 == 0:
            log.info("live: calls=%d prices=%d ETH=%s", calls.total, pw.total, book.eth_usd)
            await asyncio.sleep(1)
    for b in bg:
        b.cancel()
    for w in (calls, dests, pw):
        await w.flush()


async def refresh_cagg(c, view: str, tries: int = 10):
    """Refresh a cagg, retrying while a background policy job holds the refresh lock."""
    import asyncpg
    for i in range(tries):
        try:
            return await c.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
        except asyncpg.exceptions.LockNotAvailableError:
            await asyncio.sleep(0.5 * (i + 1))
    raise RuntimeError(f"could not refresh {view}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-hours", type=int, default=0)
    ap.add_argument("--per-hour", type=int, default=2000)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--rate", type=float, default=20.0, help="calls/second in live mode")
    ap.add_argument("--seconds", type=int, default=0)
    a = ap.parse_args()
    pool = await make_pool("tooltruth", max_size=6)
    book = PriceBook()
    try:
        book.model_prices.update(await fetch_openrouter())
    except Exception as e:  # noqa: BLE001
        log.warning("openrouter unavailable, using fallback prices: %s", e)
    if a.backfill_hours:
        await backfill(pool, a.backfill_hours, a.per_hour, book)
        async with pool.acquire() as c:
            for v in ("tool_hourly", "org_tool_hourly", "tool_dest_hourly"):
                await refresh_cagg(c, f"tooltruth.{v}")
        log.info("caggs refreshed")
    if a.live:
        await live(pool, a.rate, book, a.seconds)
    await pool.close()

if __name__ == "__main__":
    from tigerprod import setup_logging
    setup_logging(); asyncio.run(main())
