import pytest
from tooltruth import setup_db

pytestmark = pytest.mark.integration
PLANTED = {"web.summarize_url", "docs.export_pdf", "crm.lookup", "slack.upload_file", "db.export_csv",
           "jira.search", "github.search_code", "calendar.free_busy"}


async def test_migrations_idempotent(db):
    assert "01_schema.sql" in db["applied"] and await setup_db.run() == []


async def test_hypertables_caggs(db):
    p = db["pool"]
    assert await p.fetchval("SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='tooltruth'") >= 3
    assert await p.fetchval("SELECT count(*) FROM tool_hourly") > 0


async def test_suspects_only_planted(db):
    rs = await db["pool"].fetch("SELECT * FROM behaving_like_known_bad('24 hours', NULL, 0.05)")
    hits = {r["tool"] for r in rs}
    assert hits and hits <= PLANTED


async def test_new_destinations_flag_exfil(db):
    rs = await db["pool"].fetch("SELECT * FROM new_destinations('12 hours')")
    assert any("example-bad" in str(dict(r)) for r in rs)


async def test_api_endpoints(client):
    for u in ("/api/health", "/api/suspects", "/api/new-destinations", "/api/orgs", "/api/eth", "/healthz", "/readyz", "/"):
        r = await client.get(u)
        assert r.status_code == 200, (u, r.text)
    assert (await client.get("/api/series/web.summarize_url")).status_code == 200
    assert (await client.get("/api/series/no.such_tool")).status_code == 404


async def test_api_validation(client):
    r = await client.get("/api/health?hours=0")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    assert (await client.get("/api/suspects?ns=web;drop")).status_code == 422
    assert (await client.get("/api/series/DROP%20TABLE")).status_code == 422


async def test_api_key_enforced(client, monkeypatch):
    monkeypatch.setenv("TOOLTRUTH_API_KEY", "k" * 32)
    assert (await client.get("/api/health")).status_code == 401
    assert (await client.get("/api/health", headers={"Authorization": "Bearer " + "k" * 32})).status_code == 200
    assert (await client.get("/api/health", headers={"X-API-Key": "k" * 32})).status_code == 200
    assert (await client.get("/healthz")).status_code == 200  # probes stay open
