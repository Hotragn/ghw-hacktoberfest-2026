"""Re-embed semantic memory with the active embedding model.  python -m witness.reembed [--batch 64]
Safe to run repeatedly and concurrently (rows are claimed with SKIP LOCKED); also runnable as a 'reembed' queue job."""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool  # noqa: E402
from witness import embeddings  # noqa: E402
from witness.db import SYSTEM  # noqa: E402


async def run(pool, batch: int = 64, embedder=None) -> int:
    e = embedder or embeddings.get()
    total = 0
    while True:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('witness.user_id', $1, true)", SYSTEM)
                if total == 0 and e.dim:
                    await embeddings.ensure_index(conn, e)
                rows = await conn.fetch("""SELECT memory_id, text FROM memory_items WHERE embed_model IS DISTINCT FROM $1
                    ORDER BY memory_id LIMIT $2 FOR UPDATE SKIP LOCKED""", e.model, batch)
                if not rows:
                    break
                vecs = await e.embed([r["text"] for r in rows])
                await embeddings.ensure_index(conn, e)
                await conn.executemany("UPDATE memory_items SET embedding_v=$2::vector, embed_model=$3 WHERE memory_id=$1",
                                       [(r["memory_id"], embeddings.literal(v), e.model) for r, v in zip(rows, vecs)])
                await conn.execute("UPDATE embedding_models SET active = (model = $1)", e.model)
                total += len(rows)
    return total


async def _main(batch):
    pool = await make_pool("witness")
    try:
        print(f"re-embedded {await run(pool, batch)} memories with {embeddings.get().model}")
    finally:
        await pool.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=64)
    asyncio.run(_main(ap.parse_args().batch))
