import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("SCAMSHIELD_OFFLINE_BTC", "65000")  # no network in tests
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
    """Fresh scamshield schema, seed, 14-day backfill, one detector pass."""
    import asyncpg
    from tigerkit import make_pool
    from scamshield import setup_db, simulator, detector
    c = await asyncpg.connect(TEST_DB)
    await c.execute("DROP SCHEMA IF EXISTS scamshield CASCADE")
    await c.close()
    applied = await setup_db.run()
    pool = await make_pool("scamshield")
    await simulator.seed(pool)
    await simulator.backfill(pool, 14)
    await detector.run_once(pool)
    yield {"pool": pool, "applied": applied}
    await pool.close()


@pytest.fixture(scope="session")
async def client(db):
    import httpx
    from scamshield import api
    api.pool = db["pool"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as c:
        yield c
