"""Run migrations (checksum-tracked, advisory-locked).  python -m witness.setup_db
Run as the schema owner (tsdbadmin on Tiger Cloud) from CI/CD, never from the app role."""
import asyncio
import glob
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool  # noqa: E402
from tigerprod import migrate, setup_logging  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(f for f in glob.glob(os.path.join(ROOT, "sql", "[0-9]*.sql")))
REPEATABLE = ("05_queries.sql",)


async def run(schema: str = "witness"):
    pool = await make_pool(schema)
    try:
        return await migrate(pool, schema, FILES, REPEATABLE)
    finally:
        await pool.close()

if __name__ == "__main__":
    setup_logging()
    asyncio.run(run())
