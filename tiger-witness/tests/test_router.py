"""Zero-friction router: fallback order, 429/header learning, circuit breaker, budgets + new-user reserve, caches,
privacy routing, strong tier for money, queue-on-exhaustion with fair drain. Providers are httpx.MockTransport."""
import json
import uuid
from datetime import datetime, timezone
import httpx
import pytest
from witness import router as R
from witness.router import ProviderSpec, Route, Router, QuotaExhausted, BudgetPolicy

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc).timestamp()


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class Mock:
    """Scripted providers keyed by host. behaviour[host] = list of (status, headers, content) or a callable."""

    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    def __call__(self, request: httpx.Request):
        host = request.url.host
        body = json.loads(request.content)
        self.calls.append((host, body["model"]))
        b = self.behaviour.get(host, (200, {}, f"hello from {host}"))
        if callable(b):
            b = b(body)
        if isinstance(b, list):
            b = b.pop(0) if len(b) > 1 else b[0]
        status, headers, content = b
        if status == "timeout":
            raise httpx.ConnectTimeout("boom", request=request)
        if status != 200:
            return httpx.Response(status, headers=headers, json={"error": "x"})
        msg = {"role": "assistant", "content": content}
        if isinstance(content, dict):
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": content["tool"], "arguments": json.dumps(content.get("args", {}))}}]}
        return httpx.Response(200, headers=headers, json={"choices": [{"message": msg}], "usage": {"total_tokens": 100}})


def spec(name, tiers=("main", "light"), personal_ok=True, local=False, **lim):
    return ProviderSpec(name, f"https://{name}.test/v1", "k", [Route(name, f"{name}-m", frozenset(tiers), **lim)],
                        personal_ok=personal_ok, local=local)


def mk(specs, behaviour=None, clock=None, policy=None, embed=None):
    m = Mock(behaviour or {})
    r = Router(specs, policy=policy or BudgetPolicy(new_user_reserve=0), transport=httpx.MockTransport(m),
               clock=clock or Clock(), embed=embed)
    return r, m


SYS = {"role": "system", "content": "You are Witness. Reply in English. Be concise.\n"}
TOOLS = [{"name": "memory_save"}, {"name": "pay"}, {"name": "web_fetch"}]


def u(text):
    return [SYS, {"role": "user", "content": text}]


# ------------------------------------------------------------------ deterministic + parsing
@pytest.mark.parametrize("text,expect", [("help", "I'm Witness"), ("/start", "I'm Witness"), ("ping", "pong"),
                                         ("thanks!", "Anytime"), ("hello", "Hi!")])
async def test_deterministic_commands_never_call_a_provider(text, expect):
    r, m = mk([spec("groq")])
    out = await r.complete(u(text), TOOLS, "en")
    assert expect in out.content and m.calls == [] and r.stats["deterministic"] == 1


def test_parse_reset_formats():
    assert R.parse_reset("2m59.56s", 0) == pytest.approx(179.56)
    assert R.parse_reset("7.66s", 100) == pytest.approx(107.66)
    assert R.parse_reset("120ms", 0) == pytest.approx(0.12)
    assert R.parse_reset("1h2m", 0) == pytest.approx(3720)
    assert R.parse_reset("30", 10) == 40
    assert R.parse_reset(str(int((T0 + 90) * 1000)), T0) == pytest.approx(T0 + 90)
    assert R.parse_reset("garbage", 0) is None


def test_personal_and_tier_classification():
    assert not R.is_personal(u("What is the capital of France?"))
    assert R.is_personal(u("remember my wifi password"))
    assert R.is_personal([{"role": "system", "content": "sys\n- user likes tea"}, {"role": "user", "content": "hi there friend"}])
    assert R.tier_for(u("capital of France?"), TOOLS, {}) == "light"
    assert R.tier_for(u("Pay $40 at coned.com"), TOOLS, {}) == "strong"
    assert R.tier_for(u("summarize https://example.com/a for me please"), TOOLS, {}) == "main"
    assert R.tier_for(u("anything"), TOOLS, {"high_risk": True}) == "strong"


# ------------------------------------------------------------------ fallback, 429, breaker
async def test_falls_back_on_429_and_learns_reset_from_headers():
    clk = Clock()
    r, m = mk([spec("groq"), spec("cloudflare")], {
        "groq.test": (429, {"retry-after": "120", "x-ratelimit-remaining-requests": "0",
                            "x-ratelimit-reset-requests": "2m0s"}, None)}, clk)
    out = await r.complete(u("explain photosynthesis to me in detail please, with the light reactions"), [], "en")
    assert out.content == "hello from cloudflare.test"
    assert r.states["groq/groq-m"].blocked_until == pytest.approx(T0 + 120)
    m.calls.clear()
    clk.t += 30
    await r.complete(u("why is the sky blue, in physics terms, explained for a teenager please"), [], "en")
    assert [c[0] for c in m.calls] == ["cloudflare.test"]  # groq skipped while blocked: no wasted request
    clk.t += 120
    m.behaviour["groq.test"] = (200, {}, "groq back")
    out = await r.complete(u("how do tides work, in plain words, for a curious ten year old"), [], "en")
    assert out.content == "groq back"


async def test_circuit_breaker_opens_after_repeated_failures_then_recovers():
    clk = Clock()
    r, m = mk([spec("groq"), spec("cloudflare")], {"groq.test": (503, {}, None)}, clk)
    for i in range(3):
        await r.complete(u(f"tell me a fun fact about the number {i} in mathematics history"), [], "en")
    st = r.states["groq/groq-m"]
    assert st.failures == 3 and st.open_until == pytest.approx(T0 + 30)
    m.calls.clear()
    await r.complete(u("tell me a fun fact about octopuses and their three hearts"), [], "en")
    assert [c[0] for c in m.calls] == ["cloudflare.test"]
    clk.t += 31  # half-open: one probe; success closes
    m.behaviour["groq.test"] = (200, {}, "ok")
    assert (await r.complete(u("tell me a fun fact about volcanoes on other planets"), [], "en")).content == "ok"
    assert st.failures == 0 and st.open_until == 0


async def test_timeouts_count_as_failures():
    r, m = mk([spec("groq"), spec("cloudflare")], {"groq.test": ("timeout", {}, None)})
    out = await r.complete(u("what's the tallest mountain in the solar system and how tall is it"), [], "en")
    assert out.content == "hello from cloudflare.test" and r.states["groq/groq-m"].failures == 1


async def test_local_counters_respect_rpm_and_daily_caps():
    clk = Clock()
    r, m = mk([spec("groq", rpm=2, rpd=3), spec("cloudflare")], clock=clk)
    for i in range(3):
        await r.complete(u(f"question number {i} about the history of the printing press in europe"), [], "en")
    assert [c[0] for c in m.calls] == ["groq.test", "groq.test", "cloudflare.test"]  # RPM 2
    clk.t += 61
    await r.complete(u("question about gutenberg and movable type and its spread"), [], "en")
    await r.complete(u("question about paper making in china and its westward spread"), [], "en")
    assert [c[0] for c in m.calls][-2:] == ["groq.test", "cloudflare.test"]  # RPD 3 reached


async def test_tool_calls_parse_and_qwen_think_is_stripped():
    r, _ = mk([spec("groq")], {"groq.test": [(200, {}, {"tool": "memory_save", "args": {"text": "x"}}),
                                              (200, {}, "<think>secret plan</think>Final answer")]})
    c = await r.complete(u("remember that I like tea and biscuits in the afternoon"), TOOLS, "en")
    assert c.tool_calls[0].name == "memory_save" and c.tool_calls[0].arguments == {"text": "x"}
    c = await r.complete(u("tell me something nice about the ocean and its creatures"), [], "en")
    assert c.content == "Final answer"


# ------------------------------------------------------------------ tiers, privacy, strong
async def test_payments_use_only_strong_models():
    strong = ProviderSpec("groq", "https://groq.test/v1", "k", [
        Route("groq", "gpt-oss-120b", frozenset({"strong", "main"})), Route("groq", "gpt-oss-20b", frozenset({"main", "light"}))])
    r, m = mk([spec("openrouter", tiers=("strong", "main")), spec("local", tiers=("light",), local=True), strong])
    await r.complete(u("Pay $40 at coned.com for the electric bill"), TOOLS, "en")
    assert m.calls == [("groq.test", "gpt-oss-120b")]
    r.states["groq/gpt-oss-120b"].blocked_until = T0 + 600
    with pytest.raises(QuotaExhausted) as e:  # never downgrade a money turn to a weak/free-tail/local model
        await r.complete(u("Pay $40 at coned.com for the electric bill now"), TOOLS, "en")
    assert e.value.retry_at == pytest.approx(T0 + 600)


async def test_gemini_never_sees_personal_turns():
    r, m = mk([spec("gemini", personal_ok=False), spec("groq")])
    await r.complete(u("what is the boiling point of water at sea level"), [], "en")
    assert m.calls[-1][0] == "gemini.test"
    await r.complete(u("remember my sister lives in Austin"), TOOLS, "en")
    assert m.calls[-1][0] == "groq.test"


def test_gemini_and_nvidia_are_opt_in():
    base = {"GROQ_API_KEY": "g", "GEMINI_API_KEY": "x", "NVIDIA_API_KEY": "n"}
    assert [p.name for p in R.pool_from_env(base)] == ["groq"]
    names = [p.name for p in R.pool_from_env({**base, "WITNESS_GEMINI_OPT_IN": "true", "WITNESS_NVIDIA_ALLOW_PROTOTYPE": "true"})]
    assert names == ["groq", "nvidia", "gemini"]
    g = R.pool_from_env({**base, "WITNESS_GEMINI_OPT_IN": "true"})[-1]
    assert g.personal_ok is False
    full = R.pool_from_env({"GROQ_API_KEY": "g", "CLOUDFLARE_API_TOKEN": "c", "CLOUDFLARE_ACCOUNT_ID": "a",
                            "OPENROUTER_API_KEY": "o", "WITNESS_LOCAL_LLM_URL": "http://llm:8080/v1"})
    assert [p.name for p in full] == ["groq", "cloudflare", "openrouter", "local"]
    assert {r.model for r in full[0].routes} == {"openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"}


async def test_local_llama_only_serves_light_turns_as_last_resort():
    r, m = mk([spec("local", tiers=("light",), local=True), spec("groq")])
    await r.complete(u("what's a good name for a goldfish"), [], "en")
    assert m.calls[-1][0] == "groq.test"
    r.states["groq/groq-m"].blocked_until = T0 + 300
    out = await r.complete(u("what's a good name for a hamster"), [], "en")
    assert out.content == "hello from local.test"
    with pytest.raises(QuotaExhausted):  # main-tier agent turn: CPU box is too slow, queue instead
        await r.complete(u("remember that my dentist is Dr. Rao on Main Street"), TOOLS, "en")


# ------------------------------------------------------------------ caches
async def test_exact_cache_only_for_non_personal():
    r, m = mk([spec("groq")])
    for _ in range(2):
        await r.complete(u("What is the capital of France?"), [], "en")
    await r.complete(u("what is the capital of france"), [], "en")  # normalized
    assert len(m.calls) == 1 and r.stats["exact_hit"] == 2
    for _ in range(2):
        await r.complete(u("what is my capital gains tax bill"), [], "en")
    assert len(m.calls) == 3  # personal: never cached


async def test_semantic_cache_hits_paraphrase_but_not_personal():
    from witness.embeddings import HashedEmbedder
    r, m = mk([spec("groq")], embed=HashedEmbedder().embed)
    r.semantic.th = 0.80
    await r.complete(u("How tall is the Eiffel Tower in Paris?"), [], "en")
    await r.complete(u("How tall is the Eiffel Tower in Paris, France?"), [], "en")
    assert len(m.calls) == 1 and r.stats["semantic_hit"] == 1
    await r.complete(u("How tall is the Eiffel Tower compared to my house?"), [], "en")
    assert len(m.calls) == 2


async def test_tool_call_responses_and_followups_are_not_cached():
    r, m = mk([spec("groq")], {"groq.test": (200, {}, {"tool": "web_fetch", "args": {"url": "https://x"}})})
    for _ in range(2):
        await r.complete(u("fetch the weather forecast page for tomorrow please"), [], "en")
    assert len(m.calls) == 2


# ------------------------------------------------------------------ budgets
async def test_per_user_daily_budget_and_reset_at_midnight():
    clk = Clock()
    r, _ = mk([spec("groq")], clock=clk, policy=BudgetPolicy(user_daily_requests=2, new_user_reserve=0))
    tok = R.CTX.set({"user": "alice"})
    try:
        for i in range(2):
            await r.complete(u(f"riddle number {i}: what has keys but can't open locks?"), [], "en")
        with pytest.raises(QuotaExhausted) as e:
            await r.complete(u("riddle three: what gets wetter the more it dries?"), [], "en")
        assert e.value.reason == "user_budget"
        assert e.value.retry_at == datetime(2026, 10, 17, tzinfo=timezone.utc).timestamp()
        clk.t = e.value.retry_at + 1
        assert (await r.complete(u("riddle four: what has a neck but no head?"), [], "en")).content
    finally:
        R.CTX.reset(tok)


async def test_new_user_reserve_protects_capacity_for_newcomers():
    clk = Clock()
    r, _ = mk([spec("groq")], clock=clk, policy=BudgetPolicy(new_user_reserve=0.5, pool_daily_tokens=400, new_user_days=3))
    await r.budgets.first_seen("veteran", T0 - 10 * R.DAY)
    for who, ok in [("veteran", True), ("veteran", True), ("veteran", False), ("newbie", True)]:
        tok = R.CTX.set({"user": who})
        try:
            if ok:
                await r.complete(u(f"{who} asks a fresh trivia question about saturn's rings {uuid.uuid4()}"), [], "en")
            else:
                with pytest.raises(QuotaExhausted) as e:
                    await r.complete(u("veteran asks another trivia question about jupiter's storms"), [], "en")
                assert e.value.reason == "new_user_reserve"
        finally:
            R.CTX.reset(tok)


async def test_all_exhausted_reports_earliest_reset():
    clk = Clock()
    r, _ = mk([spec("groq"), spec("cloudflare")], {
        "groq.test": (429, {"retry-after": "600"}, None), "cloudflare.test": (429, {"retry-after": "90"}, None)}, clk)
    with pytest.raises(QuotaExhausted) as e:
        await r.complete(u("describe the water cycle in four short steps for a class"), [], "en")
    assert e.value.retry_at == pytest.approx(T0 + 90)
    assert "Saved, I'll reply by ~12:02 UTC." == R.eta_text(e.value.retry_at, "UTC")


def test_llm_from_env_picks_router_only_with_pool_keys(monkeypatch):
    from witness import llm
    for k in ("GROQ_API_KEY", "CLOUDFLARE_API_TOKEN", "OPENROUTER_API_KEY", "WITNESS_LOCAL_LLM_URL", "WITNESS_LLM_BASE_URL",
              "GEMINI_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert isinstance(llm.from_env(), llm.OfflineProvider)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("WITNESS_SEMANTIC_CACHE", "false")
    assert isinstance(llm.from_env(), Router)


# ------------------------------------------------------------------ queue on exhaustion (Postgres)
class _Exhausted:
    name = "exhausted"

    def __init__(self, retry_at):
        self.retry_at, self.calls = retry_at, 0

    async def complete(self, messages, tools, lang):
        self.calls += 1
        if self.retry_at:
            raise QuotaExhausted(self.retry_at)
        from witness.llm import Completion
        return Completion("here is your answer")


async def _new_user(c, name):
    r = await c.post("/api/auth/register", json={"email": f"{name}-{uuid.uuid4().hex[:6]}@t.local",
                                                 "password": "correct-horse-battery", "display_name": name})
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user_id"]


@pytest.mark.integration
async def test_web_chat_is_queued_on_exhaustion_and_drained(client, db, monkeypatch):
    import time
    from witness import api, jobs
    from witness.runtime import Agent
    from witness.worker import handlers
    monkeypatch.setenv("WITNESS_TZ", "UTC")
    p = db["pool"]
    h, uid = await _new_user(client, "quota")
    prov = _Exhausted(time.time() + 1800)
    old = api.state.get("agent")
    api.state["agent"] = Agent(p, prov)
    try:
        r = (await client.post("/api/v2/chat", json={"message": "explain how vaccines train the immune system"}, headers=h)).json()
        assert r["status"] == "deferred" and r["reply"].startswith("Saved, I'll reply by ~") and r["reply"].endswith("UTC.")
        assert await p.fetchval("SELECT count(*) FROM agent_tasks WHERE user_id=$1 AND status='deferred'", uid) == 1
        job = await p.fetchrow("SELECT * FROM jobs WHERE queue='deferred' AND payload->>'user_id'=$1", uid)
        assert job["status"] == "queued" and abs(job["run_after"].timestamp() - prov.retry_at) < 2
        # still exhausted at drain time: re-parked without burning an attempt
        await p.execute("UPDATE jobs SET run_after=now() WHERE job_id=$1", job["job_id"])
        w = jobs.Worker(p, {"deferred": handlers(p, api.state["agent"], {})["deferred"]})
        assert await w.run_once()
        j2 = await p.fetchrow("SELECT status, attempts, run_after FROM jobs WHERE job_id=$1", job["job_id"])
        assert j2["status"] == "queued" and j2["attempts"] == 0 and j2["run_after"].timestamp() > time.time() + 1000
        # quota back: drain completes the turn
        prov.retry_at = None
        await p.execute("UPDATE jobs SET run_after=now() WHERE job_id=$1", job["job_id"])
        assert await w.run_once()
        assert await p.fetchval("SELECT status FROM jobs WHERE job_id=$1", job["job_id"]) == "done"
        assert await p.fetchval("SELECT result FROM agent_tasks WHERE user_id=$1 AND status='done'", uid) == "here is your answer"
    finally:
        api.state["agent"] = old


@pytest.mark.integration
async def test_channel_message_queued_with_fair_stagger(client, db, monkeypatch):
    import time
    from witness import channels, deferral
    from witness.runtime import Agent
    monkeypatch.setenv("WITNESS_DEFER_STAGGER_S", "20")
    p = db["pool"]
    _, heavy = await _new_user(client, "heavy")
    _, light = await _new_user(client, "light")
    reset = time.time() + 600
    whens = [(await deferral.defer_turn(p, heavy, {"channel": "telegram", "external_id": "1", "text": f"m{i}"}, reset))[0]
              for i in range(3)]
    w_light, _ = await deferral.defer_turn(p, light, {"channel": "telegram", "external_id": "2", "text": "one"}, reset)
    assert [round(w - reset) for w in whens] == [0, 20, 40] and round(w_light - reset) == 0
    # light user's only message is claimed before the heavy user's 2nd and 3rd
    order = await p.fetch("""SELECT payload->>'user_id' AS u FROM jobs WHERE queue='deferred'
        AND payload->>'user_id' = ANY($1::text[]) ORDER BY run_after, job_id""", [heavy, light])
    assert [r["u"] for r in order][:2] == [heavy, light] or [r["u"] for r in order][:2] == [light, heavy]
    assert [r["u"] for r in order][2:] == [heavy, heavy]
    # same webhook retry dedupes
    _, jid = await deferral.defer_turn(p, light, {"channel": "telegram", "external_id": "2", "text": "one"}, reset)
    assert jid is None

    # end to end through channels.handle with a linked chat: user gets the Saved message via the sender
    class Sender:
        def __init__(self):
            self.sent = []

        async def send(self, ext, text, approval_id=None):
            self.sent.append(text)
    from witness.db import user_tx
    chat = f"rt-{uuid.uuid4().hex[:8]}"
    async with user_tx(p, light) as c:
        await c.execute("""INSERT INTO channel_links (user_id, channel, external_id) VALUES ($1,'telegram',$2)
                           ON CONFLICT DO NOTHING""", light, chat)
    s = Sender()
    out = await channels.handle(p, Agent(p, _Exhausted(reset)), channels.Inbound("telegram", chat, "explain black holes simply", None, "m-1"), s)
    assert out["status"] == "deferred" and s.sent[0].startswith("Saved, I'll reply by ~")


@pytest.mark.integration
async def test_pg_budget_store_persists(db):
    st = R.PgBudgetStore(db["pool"])
    await st.add("user:pgb", "2026-10-16", 1, 50)
    await st.add("user:pgb", "2026-10-16", 2, 25)
    assert await st.get("user:pgb", "2026-10-16") == (3, 75)
    a = await st.first_seen("pgb", T0)
    assert await st.first_seen("pgb", T0 + 999) == pytest.approx(a)
