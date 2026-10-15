import os
import sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("WITNESS_SIGNING_KEY", "test-signing-key-0123456789abcdef0123")
os.environ.setdefault("LOG_FORMAT", "text")
for _k in ("WITNESS_RATE_PER_MIN", "WITNESS_RATE_BURST", "WITNESS_LOGIN_RATE_PER_MIN", "WITNESS_LOGIN_BURST"):
    os.environ.setdefault(_k, "100000")
TEST_DB = os.environ.get("TEST_DB_URL")
if TEST_DB:
    os.environ["TIGER_DB_URL"] = TEST_DB  # never touch the dev/prod DB from tests


def pytest_collection_modifyitems(config, items):
    if not TEST_DB:
        skip = pytest.mark.skip(reason="TEST_DB_URL not set")
        for it in items:
            if "integration" in it.keywords:
                it.add_marker(skip)


@pytest.fixture(scope="session")
async def db():
    """Fresh schema: drop, migrate, seed the simulated dataset + 14-day scenario replay."""
    import asyncpg
    from witness import setup_db, simulator
    c = await asyncpg.connect(TEST_DB)
    await c.execute("DROP SCHEMA IF EXISTS witness CASCADE")
    await c.close()
    applied = await setup_db.run()
    await simulator.run(reset=True, with_scenarios=True)
    from tigerkit import make_pool
    pool = await make_pool("witness")
    yield {"pool": pool, "applied": applied}
    await pool.close()


@pytest.fixture(scope="session")
async def client(db):
    import httpx
    from witness import api
    api.state["pool"] = db["pool"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as c:
        yield c
