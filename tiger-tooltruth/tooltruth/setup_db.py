"""Run migrations (checksum-tracked, advisory-locked, idempotent).  python -m tooltruth.setup_db
Run as the schema owner from CI/CD; the API connects as the least-privilege role in sql/roles.sql."""
import asyncio, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool  # noqa: E402
from tigerprod import migrate, setup_logging  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(glob.glob(os.path.join(ROOT, "sql", "0*.sql")))
REPEATABLE = ("05_queries.sql",)


async def run():
    pool = await make_pool("public")
    try:
        return await migrate(pool, "tooltruth", FILES, REPEATABLE)
    finally:
        await pool.close()


async def main():  # kept for backwards compatibility
    await run()

if __name__ == "__main__":
    setup_logging(); asyncio.run(run())
