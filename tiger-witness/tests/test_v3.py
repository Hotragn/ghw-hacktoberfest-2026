"""v3: real local embeddings (semantic recall vs hashed baseline), WebAuthn passkeys with a software authenticator,
durable SKIP LOCKED job queue, short-text language detection, optional live LLM run."""
import asyncio
import json
import os
import httpx
import pytest
from witness import embeddings, i18n, jobs, passkeys
from soft_authenticator import SoftAuthenticator

FACTS = ["My sister Priya lives in Austin, Texas", "I am allergic to penicillin", "My car is a blue 2019 Honda Civic",
         "I prefer aisle seats on flights", "My dentist appointment is every six months with Dr. Rao",
         "I follow a vegetarian diet", "My son's school is Lincoln Elementary", "I pay rent of $2100 on the first of each month",
         "My gym membership is at Planet Fitness", "My partner's birthday is March 3"]
QUERIES = ["Where is my sibling based?", "Which medicines should doctors avoid giving me?", "What vehicle do I drive?",
           "Seating preference when flying?", "Who cleans my teeth?", "Do I eat meat?", "Where does my kid study?",
           "How much is my housing cost?", "Where do I work out?", "When should I celebrate my spouse?"]


# ---------------------------------------------------------------- unit
@pytest.mark.parametrize("text,lang", [
    ("Hola, ¿qué tal?", "es"), ("Merci beaucoup", "fr"), ("Danke schön", "de"), ("Obrigado pela ajuda", "pt"),
    ("Grazie mille", "it"), ("Terima kasih", "id"), ("Asante sana", "sw"), ("Teşekkürler", "tr"), ("Dank je wel", "nl"),
    ("Thanks a lot", "en"), ("Dziękuję bardzo", "pl"), ("Cảm ơn bạn", "vi"), ("Salamat po", "tl"), ("Gracias", "es"),
])
def test_short_latin_text_detection(text, lang):
    assert i18n.detect(text) == lang


def test_bound_challenge_depends_on_object():
    n = b"\x01" * 16
    assert passkeys.bound_challenge("mandate", "a" * 64, n) != passkeys.bound_challenge("mandate", "b" * 64, n)
    assert passkeys.bound_challenge("mandate", "a" * 64, n) != passkeys.bound_challenge("approval", "a" * 64, n)


async def test_openai_embedder_request():
    def h(req):
        b = json.loads(req.content)
        assert b["model"] == "text-embedding-3-small" and b["dimensions"] == 3
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1, 0]}, {"index": 0, "embedding": [1, 0, 0]}]})
    e = embeddings.OpenAIEmbedder("https://e.example/v1", "k", "text-embedding-3-small", 3, transport=httpx.MockTransport(h))
    assert await e.embed(["a", "b"]) == [[1, 0, 0], [0, 1, 0]] and e.model == "openai:text-embedding-3-small:3"


def test_from_env_defaults_to_local_model(monkeypatch):
    monkeypatch.delenv("WITNESS_EMBEDDINGS", raising=False)
    monkeypatch.delenv("WITNESS_EMBED_API_KEY", raising=False)
    e = embeddings.from_env()
    assert e.model == "local:sentence-transformers/all-MiniLM-L6-v2" and e.dim == 384


# ---------------------------------------------------------------- integration


async def _new_user(c, name):
    import uuid
    r = await c.post("/api/auth/register", json={"email": f"{name}-{uuid.uuid4().hex[:6]}@t.local",
                                                 "password": "correct-horse-battery", "display_name": name})
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user_id"]


async def _hit_at_1(client, embedder) -> float:
    embeddings.set_current(embedder)
    try:
        h, _ = await _new_user(client, "sem")
        for f in FACTS:
            assert (await client.post("/api/v2/memory", json={"text": f}, headers=h)).status_code == 201
        hits = 0
        for q, f in zip(QUERIES, FACTS):
            top = (await client.get("/api/v2/memory", params={"q": q}, headers=h)).json()[0]
            hits += top["text"] == f
        return hits / len(QUERIES)
    finally:
        embeddings.set_current(None)


@pytest.mark.integration
async def test_local_model_semantic_recall_beats_hashed(client, db):
    local, hashed = await _hit_at_1(client, embeddings.LocalEmbedder()), await _hit_at_1(client, embeddings.HashedEmbedder())
    print(f"\nhit@1 local MiniLM-384={local:.2f} hashed-256={hashed:.2f}")
    assert local >= 0.8 and local > hashed + 0.3
    idx = await db["pool"].fetch("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='memory_items' AND indexdef LIKE '%vector(384)%'")
    assert idx and "embed_model = 'local:sentence-transformers/all-MiniLM-L6-v2'" in idx[0]["indexdef"]


@pytest.mark.integration
async def test_reembed_job_migrates_rows(client, db):
    from witness import reembed
    embeddings.set_current(embeddings.HashedEmbedder())
    h, uid = await _new_user(client, "reemb")
    for f in FACTS[:4]:
        await client.post("/api/v2/memory", json={"text": f}, headers=h)
    local = embeddings.LocalEmbedder()
    embeddings.set_current(local)
    try:
        n = await reembed.run(db["pool"], batch=3, embedder=local)
        assert n >= 4
        left = await db["pool"].fetchval("SELECT count(*) FROM memory_items WHERE embed_model IS DISTINCT FROM $1", local.model)
        assert left == 0
        assert await db["pool"].fetchval("SELECT active FROM embedding_models WHERE model=$1", local.model)
        top = (await client.get("/api/v2/memory", params={"q": "What vehicle do I drive?"}, headers=h)).json()[0]
        assert "Honda" in top["text"]
    finally:
        embeddings.set_current(None)


async def _register_passkey(client, h) -> SoftAuthenticator:
    a = SoftAuthenticator()
    opts = (await client.post("/api/v2/passkeys/register/options", headers=h)).json()
    r = await client.post("/api/v2/passkeys/register/verify", json={"challenge_id": opts["challenge_id"],
                                                                    "credential": a.create(opts), "name": "test key"}, headers=h)
    assert r.status_code == 201, r.text
    return a


@pytest.mark.integration
async def test_passkey_bound_payment_mandate(client):
    h, uid = await _new_user(client, "pk")
    a = await _register_passkey(client, h)
    assert len((await client.get("/api/v2/passkeys", headers=h)).json()) == 1
    m = (await client.post("/api/v2/payment-mandates", json={"description": "coffee", "merchants": ["cafe.example"],
                                                             "max_per_txn": 10, "budget": 20}, headers=h)).json()
    ch = m["passkey_challenge"]
    from witness.payments import mandate_sha256
    assert m["content"]["passkey_required"] and ch["bound_sha256"] == mandate_sha256(m["content"])
    r = await client.post("/api/v2/chat", json={"message": "Pay $5 at cafe.example"}, headers=h)
    assert r.json()["steps"][0]["verdict"] == "blocked" and "passkey" in json.dumps(r.json()["steps"][0]["reasons"])
    bad = await client.post(f"/api/v2/payment-mandates/{m['mandate_id']}/confirm",
                            json={"challenge_id": ch["challenge_id"], "credential": a.get(ch, tamper_challenge=True)}, headers=h)
    assert bad.status_code == 401  # signature over a different object; challenge is now burned too
    ch = (await client.post(f"/api/v2/payment-mandates/{m['mandate_id']}/confirm-options", headers=h)).json()
    cred = a.get(ch)
    ok = await client.post(f"/api/v2/payment-mandates/{m['mandate_id']}/confirm", json={"challenge_id": ch["challenge_id"],
                                                                                        "credential": cred}, headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["passkey_evidence_valid"] and ok.json()["passkey_assertion"]["bound_sha256"] == ch["bound_sha256"]
    replay = await client.post(f"/api/v2/payment-mandates/{m['mandate_id']}/confirm",
                               json={"challenge_id": ch["challenge_id"], "credential": cred}, headers=h)
    assert replay.status_code == 401
    r = await client.post("/api/v2/chat", json={"message": "Pay $5 at cafe.example"}, headers=h)
    assert r.json()["steps"][0]["verdict"] == "executed"
    # offline verification: tampering with the stored evidence's bound hash breaks it
    ev = ok.json()["passkey_assertion"]
    assert passkeys.verify_evidence(ev) and not passkeys.verify_evidence({**ev, "bound_sha256": "0" * 64})


@pytest.mark.integration
async def test_high_risk_approval_requires_passkey(client):
    from witness import api, llm
    from witness.runtime import Agent
    from witness.tools import Services
    sent = []
    api.state["agent"] = Agent(api.state["pool"], llm.OfflineProvider(), Services(smtp_send=lambda cfg, m: sent.append(m)))
    h, uid = await _new_user(client, "pka")
    a = await _register_passkey(client, h)
    await client.put("/api/v2/connectors", json={"kind": "smtp", "config": {"host": "smtp.example", "username": "u"}}, headers=h)
    res = (await client.post("/api/v2/chat", json={"message": "email bob@example.com saying hi"}, headers=h)).json()
    aid = res["approval_id"]
    inbox = (await client.get("/api/v2/approvals", headers=h)).json()
    assert inbox[0]["risk"] == "high"
    assert (await client.post(f"/api/v2/approvals/{aid}", json={"approve": True}, headers=h)).status_code == 428
    ch = (await client.post(f"/api/v2/approvals/{aid}/passkey-options", headers=h)).json()
    r = await client.post(f"/api/v2/approvals/{aid}", json={"approve": True, "challenge_id": ch["challenge_id"],
                                                            "credential": a.get(ch)}, headers=h)
    assert r.status_code == 200 and r.json()["steps"][0]["verdict"] == "executed" and len(sent) == 1
    done = (await client.get("/api/v2/approvals", params={"status": "approved"}, headers=h)).json()
    assert passkeys.verify_evidence(done[0]["passkey_assertion"])


@pytest.mark.integration
async def test_queue_dedupe_concurrency_retry_dead_letter(db):
    p = db["pool"]
    await p.execute("DELETE FROM jobs WHERE queue LIKE 't-%'")
    async with p.acquire() as c:
        assert await jobs.enqueue(c, "t-dedupe", {"x": 1}, "telegram:42")
        assert await jobs.enqueue(c, "t-dedupe", {"x": 1}, "telegram:42") is None  # webhook retry
        for i in range(40):
            await jobs.enqueue(c, "t-work", {"i": i})
    seen = []

    async def work(payload):
        await asyncio.sleep(0.005)
        seen.append(payload["i"])
    workers = [jobs.Worker(p, {"t-work": work}, f"w{n}") for n in range(4)]
    counts = await asyncio.gather(*(w.drain() for w in workers))
    assert sorted(seen) == list(range(40)) and sum(counts) == 40  # each job exactly once across 4 concurrent workers
    assert sum(1 for c in counts if c) >= 2  # work was actually spread across workers

    async with p.acquire() as c:
        await jobs.enqueue(c, "t-fail", {"k": 1}, max_attempts=2)

    async def boom(_):
        raise RuntimeError("downstream 500")
    w = jobs.Worker(p, {"t-fail": boom})
    assert await w.run_once()
    row = await p.fetchrow("SELECT status, attempts, run_after > now() AS backoff FROM jobs WHERE queue='t-fail'")
    assert row["status"] == "queued" and row["attempts"] == 1 and row["backoff"]
    await p.execute("UPDATE jobs SET run_after=now() WHERE queue='t-fail'")
    assert await w.run_once()
    row = await p.fetchrow("SELECT status, last_error FROM jobs WHERE queue='t-fail'")
    assert row["status"] == "dead" and "downstream 500" in row["last_error"]

    async with p.acquire() as c:
        await jobs.enqueue(c, "t-stale", {})
    await jobs.claim(p, ["t-stale"], "crashed-worker")
    await p.execute("UPDATE jobs SET locked_at = now() - interval '10 minutes' WHERE queue='t-stale'")
    assert await jobs.reap_stale(p, 300) == 1
    assert await p.fetchval("SELECT status FROM jobs WHERE queue='t-stale'") == "queued"


@pytest.mark.integration
async def test_webhook_is_acked_before_processing(client, db, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "q")
    upd = {"update_id": 991122, "message": {"chat": {"id": 31337}, "text": "hi"}}
    for _ in range(2):  # Telegram retries deliver the same update_id
        r = await client.post("/channels/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "q"})
        assert r.status_code == 200
    rows = await db["pool"].fetch("SELECT status FROM jobs WHERE dedupe_key='telegram:991122'")
    assert [r["status"] for r in rows] == ["queued"]


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("WITNESS_LIVE_LLM_URL"), reason="set WITNESS_LIVE_LLM_URL to an OpenAI-compatible server")
async def test_live_llm_end_to_end(client, db):
    """Runs the real agent loop through a live OpenAI-compatible model (docs/LIVE_RUN.md records a run)."""
    from witness import api, llm
    from witness.runtime import Agent
    from witness.tools import Services
    prov = llm.OpenAICompatProvider(os.environ["WITNESS_LIVE_LLM_URL"], os.environ.get("WITNESS_LIVE_LLM_KEY", "local"),
                                    os.environ.get("WITNESS_LIVE_LLM_MODEL", "local"), timeout=300)
    h, uid = await _new_user(client, "live")
    agent = Agent(api.state["pool"], prov, Services())
    res = await agent.run(uid, "Please remember that my favourite airline seat is 14C, an aisle seat.")
    print("\nLIVE RESULT:", json.dumps(res, indent=1))
    assert any(s["tool"] == "memory_save" and s["verdict"] == "executed" for s in res["steps"])
    mem = (await client.get("/api/v2/memory", headers=h)).json()
    assert any("14C" in m["text"] for m in mem)


class _Looping:
    """Simulates a weak model that keeps retrying the same blocked call."""
    name = "looping"

    async def complete(self, messages, tools, lang):
        from witness.llm import Completion, ToolCall
        if not tools:
            return Completion("ok")
        return Completion(None, [ToolCall(f"c{len(messages)}", "pay", {"merchant": "evil.example", "amount": 500})])


@pytest.mark.integration
async def test_retry_storm_is_cut_short(client):
    from witness import api
    from witness.runtime import Agent
    h, uid = await _new_user(client, "loop")
    res = await Agent(api.state["pool"], _Looping()).run(uid, "pay evil.example 500")
    assert len(res["steps"]) == 1 and res["steps"][0]["verdict"] == "blocked"
    assert res["reply"].startswith("I didn't do that") and "no active payment mandate" in res["reply"]
