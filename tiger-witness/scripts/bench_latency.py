"""Measure p50/p95 of the latency-critical paths that can run without cloud credentials.
    TEST_DB_URL=postgres://... python scripts/bench_latency.py [N]
Paths: edge HMAC verify, ASGI /health, edge-signed Telegram webhook -> durable enqueue (real Postgres),
/api/v2/chat/stream time-to-first-byte with a mocked Groq (app overhead only), pooled vs fresh DB connection."""
import asyncio
import json
import os
import statistics
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("WITNESS_SIGNING_KEY", "bench-signing-key-0123456789abcdef0123")
os.environ.setdefault("WITNESS_EMBEDDINGS", "hashed")
os.environ.setdefault("LOG_LEVEL", "WARNING")
for k in ("WITNESS_RATE_PER_MIN", "WITNESS_RATE_BURST", "WITNESS_SENDER_RATE_PER_MIN", "WITNESS_SENDER_BURST"):
    os.environ[k] = "10000000"
os.environ["TIGER_DB_URL"] = os.environ["TEST_DB_URL"]
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "bench-tg"
os.environ["WITNESS_EDGE_SECRET"] = "bench-edge"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300


def pct(xs):
    xs = sorted(xs)
    return {"p50_ms": round(statistics.median(xs), 3), "p95_ms": round(xs[int(len(xs) * 0.95) - 1], 3), "n": len(xs)}


async def timeit(fn, n=N):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        await fn()
        out.append((time.perf_counter() - t) * 1000)
    return pct(out)


async def main():
    import logging
    logging.disable(logging.INFO)
    import asyncpg
    import httpx
    from witness import api, edge, llm
    from witness.router import BudgetPolicy, ProviderSpec, Route, Router
    from witness.runtime import Agent
    res = {}

    body = b'{"update_id":1,"message":{"chat":{"id":1},"text":"hi"}}'

    async def ver():
        n = uuid.uuid4().hex
        ts = str(int(time.time()))
        edge.verify("k", ts, n, edge.sign("k", ts, n, "POST", "/p", body), "POST", "/p", body)
    res["edge_hmac_sign+verify"] = await timeit(ver, 2000)

    async with api.lifespan(api.app):
        api.state["provider"] = llm.OfflineProvider()
        tr = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=tr, base_url="http://bench") as c:
            res["asgi_GET_/health"] = await timeit(lambda: c.get("/health"))
            i = [0]

            async def hook():
                i[0] += 1
                b = json.dumps({"update_id": 7_000_000 + i[0], "message": {"chat": {"id": 4242}, "text": "hi"}}).encode()
                ts, n = str(int(time.time())), uuid.uuid4().hex
                h = {"X-Telegram-Bot-Api-Secret-Token": "bench-tg", "content-type": "application/json",
                     "x-witness-edge-ts": ts, "x-witness-edge-nonce": n,
                     "x-witness-edge-sig": edge.sign("bench-edge", ts, n, "POST", "/channels/telegram/webhook", b)}
                r = await c.post("/channels/telegram/webhook", content=b, headers=h)
                assert r.status_code == 200, r.text
            res["webhook_verify+enqueue(pg)"] = await timeit(hook)

            sse = ("data: " + json.dumps({"choices": [{"delta": {"content": "hey"}}]}) + "\n\ndata: [DONE]\n\n").encode()
            rt = Router([ProviderSpec("groq", "https://groq.test/v1", "k", [Route("groq", "m", frozenset({"light"}))])],
                        policy=BudgetPolicy(new_user_reserve=0, user_daily_requests=10**9, user_daily_tokens=10**12),
                        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=sse)))
            api.state["agent"] = Agent(api.state["pool"], rt, None)
            r = await c.post("/api/auth/register", json={"email": f"b{uuid.uuid4().hex[:6]}@t.local",
                                                         "password": "correct-horse-battery", "display_name": "b"})
            h = {"Authorization": "Bearer " + r.json()["token"]}
            k = [0]

            async def ttfb():
                k[0] += 1
                async with c.stream("POST", "/api/v2/chat/stream", json={"message": f"say hi number {k[0]}"},
                                    headers=h) as s:
                    async for _ in s.aiter_raw():
                        break
            res["chat_stream_ttfb(mock_groq)"] = await timeit(ttfb, 200)
            await rt.aclose()

    pool = await asyncpg.create_pool(os.environ["TEST_DB_URL"], min_size=2, max_size=2)
    res["db_pooled_SELECT1"] = await timeit(lambda: pool.fetchval("SELECT 1"))
    await pool.close()

    async def fresh():
        conn = await asyncpg.connect(os.environ["TEST_DB_URL"])
        await conn.fetchval("SELECT 1")
        await conn.close()
    res["db_fresh_conn_SELECT1"] = await timeit(fresh, 100)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
