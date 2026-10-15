"""Live pricing ingestor.
- OpenRouter public models API (no key): https://openrouter.ai/api/v1/models -> USD per token.
- Coinbase Advanced Trade public WS ticker (no key): ETH-USD (USDC books are aliased to USD on Coinbase).
Writes to tooltruth.prices and keeps an in-memory cache (PriceBook) for the simulator."""
from __future__ import annotations
import argparse, asyncio, logging, os, sys, time
from datetime import datetime, timezone
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import BatchWriter, coinbase_ticker, make_pool  # noqa: E402

log = logging.getLogger("pricing")
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
# Verified present on OpenRouter /api/v1/models on 2026-10-15. Missing ids fall back to FALLBACK pricing.
DEFAULT_MODELS = ["openai/gpt-4o-mini", "anthropic/claude-haiku-5.5", "google/gemini-3.8-flash",
                  "meta-llama/llama-3.1-8b-instruct", "deepseek/deepseek-v4.1-flash"]
FALLBACK = {"prompt": 1.5e-7, "completion": 6e-7}


class PriceBook:
    def __init__(self):
        self.model_prices: dict[str, dict[str, float]] = {}
        self.eth_usd: float | None = None
        self.eth_ts: float = 0.0

    def token_cost(self, model: str, tin: int, tout: int) -> float:
        p = self.model_prices.get(model, FALLBACK)
        return tin * p["prompt"] + tout * p["completion"]


async def fetch_openrouter(models: list[str] | None = None) -> dict[str, dict[str, float]]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(OPENROUTER_MODELS)
        r.raise_for_status()
    out = {}
    for m in r.json()["data"]:
        pr = m.get("pricing") or {}
        try:
            p, c_ = float(pr.get("prompt", 0)), float(pr.get("completion", 0))
        except (TypeError, ValueError):
            continue
        if p < 0 or c_ < 0:  # openrouter uses -1 for router/auto models
            continue
        out[m["id"]] = {"prompt": p, "completion": c_}
    if models:
        out = {k: v for k, v in out.items() if k in models} or out
    return out


async def openrouter_loop(book: PriceBook, writer: BatchWriter | None, every: int = 600):
    while True:
        try:
            prices = await fetch_openrouter()
            book.model_prices.update(prices)
            now = datetime.now(timezone.utc)
            if writer:
                for mid in DEFAULT_MODELS:
                    if mid in prices:
                        for kind in ("prompt", "completion"):
                            await writer.add((now, "openrouter", f"{mid}:{kind}", prices[mid][kind]))
            log.info("openrouter: %d models priced", len(prices))
        except Exception as e:  # noqa: BLE001
            log.warning("openrouter fetch failed: %s", e)
        await asyncio.sleep(every)


async def coinbase_loop(book: PriceBook, writer: BatchWriter | None, products=("ETH-USD",)):
    async for t in coinbase_ticker(products):
        book.eth_usd, book.eth_ts = t["price"], time.time()
        if writer:
            ts = datetime.fromisoformat(t["ts"].replace("Z", "+00:00")[:26] + "+00:00") if t["ts"] else datetime.now(timezone.utc)
            await writer.add((ts, "coinbase", t["product"], t["price"]))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print live prices, do not touch the DB")
    ap.add_argument("--seconds", type=int, default=0, help="stop after N seconds (0 = forever)")
    a = ap.parse_args()
    book, writer = PriceBook(), None
    if not a.dry_run:
        pool = await make_pool("tooltruth")
        writer = BatchWriter(pool, "prices", ["ts", "source", "symbol", "price"], "tooltruth", max_rows=200)
    tasks = [asyncio.create_task(openrouter_loop(book, writer)), asyncio.create_task(coinbase_loop(book, writer))]
    if writer:
        tasks.append(asyncio.create_task(writer.run_timer()))
    start = time.time()
    while not a.seconds or time.time() - start < a.seconds:
        await asyncio.sleep(5)
        sample = {k: book.model_prices[k] for k in DEFAULT_MODELS if k in book.model_prices}
        log.info("ETH-USD=%s models=%s rows=%s", book.eth_usd, sample, writer.total if writer else "-")
    for t in tasks:
        t.cancel()
    if writer:
        await writer.flush()

if __name__ == "__main__":
    from tigerprod import setup_logging
    setup_logging(); asyncio.run(main())
