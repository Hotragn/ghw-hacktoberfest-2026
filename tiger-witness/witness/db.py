"""Tenant-scoped database access. Every v2 query runs inside `user_tx`, which sets the transaction-local GUC
witness.user_id that the FORCE ROW LEVEL SECURITY policies key on, so a bug in a WHERE clause cannot leak rows."""
from __future__ import annotations
from contextlib import asynccontextmanager
import asyncpg

SYSTEM = "__system__"


@asynccontextmanager
async def user_tx(pool: asyncpg.Pool, user_id: str):
    if not user_id:
        raise ValueError("user_id required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('witness.user_id', $1, true)", user_id)
            yield conn


@asynccontextmanager
async def system_tx(pool: asyncpg.Pool):
    """Cross-tenant routing only (e.g. mapping a Telegram chat id to its owner). Never used for user data reads."""
    async with user_tx(pool, SYSTEM) as conn:
        yield conn
