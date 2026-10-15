import pytest
from scamshield import setup_db

pytestmark = pytest.mark.integration


async def test_migrations_idempotent(db):
    assert "01_schema.sql" in db["applied"] and await setup_db.run() == []


async def test_consent_gate_dropped_pending_household(db):
    p = db["pool"]
    assert await p.fetchval("SELECT count(*) FROM home_signals WHERE household_id='hh-005'") == 0
    assert await p.fetchval("SELECT count(*) FROM home_signals WHERE household_id='hh-001'") > 0


async def test_detector_outcomes(db):
    p = db["pool"]
    risk = {r["household_id"]: r for r in await p.fetch("SELECT DISTINCT ON (household_id) * FROM alerts ORDER BY household_id, ts DESC")}
    assert risk["hh-001"]["risk_score"] >= 0.9 and "Pig" in risk["hh-001"]["storyline"]
    assert risk["hh-002"]["risk_score"] >= 0.5 and "Tech" in risk["hh-002"]["storyline"]
    assert "hh-003" not in risk and "hh-004" not in risk and "hh-005" not in risk
    assert all(r["delivery"].startswith(("simulated", "suppressed")) for r in risk.values())
    assert all("[SIMULATED - not sent]" in r["message"] for r in risk.values())


async def test_api_reads(client):
    for u in ("/api/households", "/api/alerts", "/api/fake-profit", "/api/btc", "/api/consent-log",
              "/api/households/hh-001/features", "/api/households/hh-001/storylines", "/healthz", "/readyz", "/"):
        r = await client.get(u)
        assert r.status_code == 200, (u, r.text)


async def test_api_validation(client):
    assert (await client.get("/api/households/../../etc/features")).status_code in (404, 422)
    assert (await client.get("/api/households/hh-001/features?days=0")).status_code == 422
    r = await client.post("/api/households/hh-003/pause", json={"actor": "", "hours": 24})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    assert (await client.post("/api/households/hh-999/pause", json={"actor": "x"})).status_code == 404
    assert (await client.post("/api/households/hh-999/revoke", json={"actor": "x"})).status_code == 404


async def test_pause_and_revoke_are_audited_and_delete(client, db):
    p = db["pool"]
    assert (await client.post("/api/households/hh-003/pause", json={"actor": "Margaret (sim)", "hours": 2})).status_code == 200
    assert await p.fetchval("SELECT paused_until > now() FROM households WHERE household_id='hh-003'")
    before = await p.fetchval("SELECT count(*) FROM home_signals WHERE household_id='hh-004'")
    assert before > 0
    r = await client.post("/api/households/hh-004/revoke", json={"actor": "Ernest (sim)"})
    assert r.status_code == 200
    assert await p.fetchval("SELECT count(*) FROM home_signals WHERE household_id='hh-004'") == 0
    assert await p.fetchval("SELECT consent_allows('hh-004','calls')") is False
    assert await p.fetchval("SELECT count(*) FROM consent_log WHERE household_id='hh-004' AND action LIKE 'revoke%'") >= 1


async def test_api_key_enforced(client, monkeypatch):
    monkeypatch.setenv("SCAMSHIELD_API_KEY", "s" * 32)
    assert (await client.get("/api/alerts")).status_code == 401
    assert (await client.get("/api/alerts", headers={"Authorization": "Bearer " + "s" * 32})).status_code == 200
    assert (await client.get("/healthz")).status_code == 200
