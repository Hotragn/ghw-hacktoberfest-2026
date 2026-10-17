"""Shared helpers: asyncpg pool, batched writer, Coinbase ticker stream, keyless embeddings.
Copied verbatim into each project folder so each folder is self-contained."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import re
from typing import AsyncIterator, Sequence

import asyncpg

log = logging.getLogger("tigerkit")
COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"


def load_env(path: str = ".env") -> None:
    for p in (path, os.path.join(os.path.dirname(__file__), ".env")):
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))
            return


def db_url() -> str:
    load_env()
    url = os.environ.get("TIGER_DB_URL")
    if not url:
        raise SystemExit("TIGER_DB_URL not set (copy .env.example to .env; get it via `tiger db uri`)")
    return url


def tls_args(url: str) -> tuple[str, dict]:
    """Strict TLS for remote Postgres. `sslmode=verify-full` (in the URL or via TIGER_DB_SSLMODE) becomes an explicit
    SSLContext: CERT_REQUIRED + hostname check against the system CA bundle (Tiger Cloud uses a public CA) or
    PGSSLROOTCERT / sslrootcert= when given. Other modes are passed through untouched to asyncpg."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    u = urlsplit(url)
    q = dict(parse_qsl(u.query))
    mode = os.environ.get("TIGER_DB_SSLMODE") or q.get("sslmode")
    if mode != "verify-full":
        return url, {}
    import ssl
    ctx = ssl.create_default_context(cafile=q.pop("sslrootcert", None) or os.environ.get("PGSSLROOTCERT") or None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname, ctx.verify_mode = True, ssl.CERT_REQUIRED
    q.pop("sslmode", None)
    return urlunsplit(u._replace(query=urlencode(q))), {"ssl": ctx}


async def make_pool(schema: str, min_size: int = 1, max_size: int = 5) -> asyncpg.Pool:
    # search_path as a startup parameter survives asyncpg's RESET ALL on connection release.
    # Pooled, long-lived TLS connections: the handshake (~3 RTT to us-east-1) is paid once per connection, not per
    # query; min_size keeps warm connections ready, idle ones are recycled after 5 min.
    url, extra = tls_args(db_url())
    return await asyncpg.create_pool(url, min_size=min_size, max_size=max(min_size, max_size), command_timeout=60,
                                     max_inactive_connection_lifetime=300.0,
                                     server_settings={"search_path": f"{schema}, public",
                                                      "application_name": f"tiger-{schema}"}, **extra)


async def apply_sql_files(pool: asyncpg.Pool, files: Sequence[str]) -> None:
    async with pool.acquire() as conn:
        for f in files:
            sql = open(f).read()
            # continuous aggregate creation cannot run inside a transaction block -> split on marker
            for stmt in sql.split("-- @@"):
                if stmt.strip():
                    await conn.execute(stmt)
            log.info("applied %s", f)


class BatchWriter:
    """Buffers rows and flushes with COPY every `max_rows` or `max_wait` seconds. Retries on failure."""

    def __init__(self, pool: asyncpg.Pool, table: str, columns: Sequence[str], schema: str,
                 max_rows: int = 500, max_wait: float = 1.0):
        self.pool, self.table, self.columns, self.schema = pool, table, list(columns), schema
        self.max_rows, self.max_wait = max_rows, max_wait
        self.buf: list[tuple] = []
        self.lock = asyncio.Lock()
        self.total = 0

    async def add(self, row: tuple) -> None:
        self.buf.append(row)
        if len(self.buf) >= self.max_rows:
            await self.flush()

    async def flush(self) -> None:
        async with self.lock:
            if not self.buf:
                return
            rows, self.buf = self.buf, []
            for attempt in range(5):
                try:
                    async with self.pool.acquire() as conn:
                        await conn.copy_records_to_table(self.table, records=rows, columns=self.columns,
                                                         schema_name=self.schema)
                    self.total += len(rows)
                    return
                except (OSError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as e:
                    wait = min(30, 2 ** attempt) + random.random()
                    log.warning("flush %s failed (%s), retry in %.1fs", self.table, e, wait)
                    await asyncio.sleep(wait)
            log.error("dropping %d rows for %s after retries", len(rows), self.table)

    async def run_timer(self) -> None:
        while True:
            await asyncio.sleep(self.max_wait)
            await self.flush()


async def coinbase_ticker(products: Sequence[str]) -> AsyncIterator[dict]:
    """Yield {'product','price','ts'} from Coinbase Advanced Trade public ticker channel (no key).
    Reconnects forever with exponential backoff + jitter."""
    import websockets

    backoff = 1.0
    while True:
        try:
            async with websockets.connect(COINBASE_WS, ping_interval=20, max_size=2**22) as ws:
                for ch in ("ticker", "heartbeats"):
                    await ws.send(json.dumps({"type": "subscribe", "product_ids": list(products), "channel": ch}))
                backoff = 1.0
                log.info("coinbase connected %s", products)
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("channel") != "ticker":
                        continue
                    for ev in msg.get("events", []):
                        for t in ev.get("tickers", []):
                            yield {"product": t["product_id"], "price": float(t["price"]),
                                   "ts": msg.get("timestamp")}
        except Exception as e:  # noqa: BLE001 - network loop must survive anything
            log.warning("coinbase ws error %s; reconnect in %.1fs", e, backoff)
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 60)


def text_embedding(text: str, dim: int = 256) -> list[float]:
    """Keyless, deterministic hashed bag-of-words + bigram embedding (L2-normalised).
    Good enough for storyline similarity demos; swap for a real model via pgai later."""
    v = [0.0] * dim
    toks = re.findall(r"[a-z0-9]+", text.lower())
    grams = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def vec_literal(v: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
