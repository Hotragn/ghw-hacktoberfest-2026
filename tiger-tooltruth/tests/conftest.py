import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("LOG_FORMAT", "text")
TEST_DB = os.environ.get("TEST_DB_URL")
if TEST_DB:
    os.environ["TIGER_DB_URL"] = TEST_DB


def pytest_collection_modifyitems(config, items):
    if not TEST_DB:
        for it in items:
            if "integration" in it.keywords:
                it.add_marker(pytest.mark.skip(reason="TEST_DB_URL not set"))


@pytest.fixture(scope="session")
async def db():
    """Fresh tooltruth schema + 12h offline backfill (fallback prices, no network) + fingerprints."""
    import asyncpg
    from datetime import datetime, timedelta, timezone
    from tigerkit import make_pool
    from tooltruth import setup_db, simulator, fingerprint
    from tooltruth.pricing import PriceBook
    c = await asyncpg.connect(TEST_DB)
    await c.execute("DROP SCHEMA IF EXISTS tooltruth CASCADE")
    await c.close()
    applied = await setup_db.run()
    pool = await make_pool("tooltruth", max_size=6)
    await simulator.backfill(pool, 12, 1500, PriceBook())
    async with pool.acquire() as conn:
        for v in ("tool_hourly", "org_tool_hourly", "tool_dest_hourly"):
            await simulator.refresh_cagg(conn, f"tooltruth.{v}")
    await fingerprint.seed_known_bad(pool)
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    for i in range(11, -1, -1):
        await fingerprint.fingerprint_window(pool, end - timedelta(hours=i + 1), end - timedelta(hours=i))
    yield {"pool": pool, "applied": applied}
    await pool.close()


@pytest.fixture(scope="session")
async def client(db):
    import httpx
    from tooltruth import api
    api.pool = db["pool"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as c:
        yield c
