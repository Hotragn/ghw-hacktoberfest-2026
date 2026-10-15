"""Integration tests against a real TimescaleDB + pgvector (TEST_DB_URL). Exercise SQL, caggs, agent, API, auth."""
import pytest
from witness import agent, setup_db

pytestmark = pytest.mark.integration
PW = "witness-demo-pass"


async def login(client, who="maya"):
    r = await client.post("/api/auth/login", json={"email": f"{who}@demo.witness.local", "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


async def test_migrations_idempotent(db):
    assert "01_schema.sql" in db["applied"]
    assert await setup_db.run() == []  # second run applies nothing


async def test_hypertables_and_caggs(db):
    p = db["pool"]
    hts = {r["hypertable_name"] for r in await p.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema='witness'")}
    assert {"life_events", "actions", "inbound"} <= hts
    caggs = {r["view_name"] for r in await p.fetch("SELECT view_name FROM timescaledb_information.continuous_aggregates WHERE view_schema='witness'")}
    assert {"spend_daily", "spend_monthly", "actions_hourly"} <= caggs
    assert await p.fetchval("SELECT count(*) FROM spend_monthly WHERE user_id='u-maya'") > 10


async def test_scenario_outcomes(db):
    p = db["pool"]
    d = {r["request"]: r["decision"] for r in await p.fetch("SELECT request, decision FROM actions WHERE user_id='u-maya'")}
    assert d["pay the electric bill"] == "executed_simulated"          # pgvector recall resolved ConEd
    assert d["pay my coned bill $412"] == "needs_approval"              # own-baseline anomaly
    assert d["reply to buyer jo sure, pick up at my place tonight, here is my address"] == "blocked"
    assert d["book a table for four at lucia's for $110"] == "needs_approval"  # one-time mandate used up
    assert d["pay my water bill $60"] == "needs_approval"               # uncited assumption
    g = [r["decision"] for r in await p.fetch("SELECT decision FROM actions WHERE user_id='u-grace' AND source LIKE 'inbound:%' ORDER BY ts")]
    assert g == ["blocked", "blocked", "executed_simulated"]


async def test_electric_bill_cites_evidence(db):
    r = await db["pool"].fetchrow("SELECT evidence, merchant FROM actions WHERE request='pay the electric bill'")
    assert r["merchant"] == "ConEd" and len(r["evidence"]) >= 1


async def test_chain_verifies_and_tamper_detected(db):
    p = db["pool"]
    v = await agent.verify(p, "u-maya")
    assert v["ok"] and v["receipts"] > 20
    with pytest.raises(Exception, match="append-only"):
        await p.execute("UPDATE receipts SET payload='{}' WHERE user_id='u-maya' AND seq=1")
    with pytest.raises(Exception, match="append-only"):
        await p.execute("DELETE FROM receipts WHERE user_id='u-maya'")


async def test_replay_reproduces_and_diffs(db):
    r = await agent.replay(db["pool"], "u-maya", 30)
    assert r["actions"] > 0 and r["reproduced_exactly"] == r["actions"] and r["changed"] == 0
    r2 = await agent.replay(db["pool"], "u-maya", 30, mandate_patch=[{"mandate_id": "m-maya-market", "daily_action_budget": 2}])
    assert r2["changed"] > 0 and all(d["would_be"] == "needs_approval" for d in r2["diffs"])


async def test_insight_queries(db):
    p = db["pool"]
    creep = {r["merchant"]: r for r in await p.fetch("SELECT * FROM subscription_creep('u-maya')")}
    assert "Netflix" in creep and creep["Netflix"]["pct_change"] > 40
    idle = [r["merchant"] for r in await p.fetch("SELECT * FROM idle_subscriptions('u-maya')")]
    assert "Equinox" in idle and "Spotify" not in idle
    drift = {r["mandate_id"]: r for r in await p.fetch("SELECT * FROM consent_drift('u-maya')")}
    assert drift["m-maya-market"]["recent"] > drift["m-maya-market"]["prior"]


async def test_auth_required_and_isolation(client):
    assert (await client.get("/api/actions")).status_code == 401
    assert (await client.get("/api/actions", headers={"Authorization": "Bearer nope"})).status_code == 401
    h = await login(client, "dev")
    acts = (await client.get("/api/actions", headers=h)).json()
    assert acts and all("maya" not in a["request"] for a in acts)
    from witness import api
    mid = await api.state["pool"].fetchval("SELECT action_id FROM actions WHERE user_id='u-maya' AND decision='needs_approval' LIMIT 1")
    r = await client.post(f"/api/actions/{mid}/approve", headers=h)
    assert r.status_code == 409  # dev cannot see/approve maya's action
    assert (await client.post("/api/mandates/m-maya-bills/revoke", headers=h)).status_code == 404


async def test_bad_login_and_validation(client):
    r = await client.post("/api/auth/login", json={"email": "maya@demo.witness.local", "password": "wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "http_401"
    h = await login(client)
    r = await client.post("/api/requests", json={"text": "x"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    r = await client.post("/api/mandates", json={"kind": "forever", "action": "pay_bill"}, headers=h)
    assert r.status_code == 422
    r = await client.post("/api/replay", json={"params": {"drop_tables": 1}}, headers=h)
    assert r.status_code == 422
    assert "x-request-id" in r.headers


async def test_register_request_approve_flow(client):
    r = await client.post("/api/auth/register", json={"email": "new.user@example.com", "password": "a-long-password-123",
                                                      "display_name": "New", "home_channel": "slack"})
    assert r.status_code == 201
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert (await client.post("/api/auth/register", json={"email": "new.user@example.com", "password": "a-long-password-123",
                                                          "display_name": "Dup"})).status_code == 409
    # no mandates yet -> needs approval
    r = await client.post("/api/requests", json={"text": "book a table at lucia's for $80"}, headers=h)
    a = r.json()
    assert a["decision"] == "needs_approval"
    r = await client.post(f"/api/actions/{a['action_id']}/approve", headers=h)
    assert r.status_code == 200 and r.json()["execution"]["simulated"] is True
    assert (await client.post(f"/api/actions/{a['action_id']}/approve", headers=h)).status_code == 409  # once only
    # add a mandate, now the same kind of request executes
    r = await client.post("/api/mandates", json={"kind": "standing", "action": "book", "counterparty": "lucia*",
                                                 "max_amount": 100, "daily_action_budget": 5}, headers=h)
    assert r.status_code == 201
    a2 = (await client.post("/api/requests", json={"text": "book a table at lucia's for $80"}, headers=h)).json()
    assert a2["decision"] == "needs_approval"  # no history with merchant + standing -> still asks (own_baseline)
    v = (await client.get("/api/receipts/verify", headers=h)).json()
    assert v["ok"] and v["receipts"] == 3
    assert (await client.post("/api/auth/logout", headers=h)).status_code == 200
    assert (await client.get("/api/me", headers=h)).status_code == 401


async def test_inbound_scam_via_api(client):
    h = await login(client, "grace")
    r = await client.post("/api/inbound", headers=h, json={"channel": "sms", "sender": "+1-555-0100",
        "body": "Final notice: unpaid toll. Pay $300 in gift cards to E-ZPass today, urgent"})
    assert r.status_code == 200 and r.json()["decision"] == "blocked"


async def test_health(client):
    assert (await client.get("/healthz")).json() == {"ok": True}
    assert (await client.get("/readyz")).status_code == 200
