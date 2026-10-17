"""Low-latency + secure public deployment: edge HMAC with replay protection, provider signatures, security headers,
strict CORS, per-sender limits, verify-full TLS, light-turn streaming with Groq first."""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

import tigerkit
from tigerprod import RateLimiter
from witness import channels, edge
from witness import router as R
from witness.config import db_tls_problem
from witness.router import BudgetPolicy, ProviderSpec, Route, Router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = 1_800_000_000


def signed(secret, method, path_qs, body, ts=NOW, nonce="ab" * 16):
    return str(ts), nonce, edge.sign(secret, str(ts), nonce, method, path_qs, body)


def test_edge_verify_ok_stale_bad_replay():
    n = edge.NonceCache(ttl=120)
    ts, nonce, sig = signed("k", "POST", "/channels/telegram/webhook", b"{}")
    def v(**kw):
        return edge.verify(kw.get("secret", "k"), kw.get("ts", ts), kw.get("nonce", nonce), kw.get("sig", sig),
                           "POST", kw.get("path", "/channels/telegram/webhook"), kw.get("body", b"{}"),
                           now=kw.get("now", NOW), nonces=n)
    assert v(nonce="cd" * 16, sig=edge.sign("k", ts, "cd" * 16, "POST", "/channels/telegram/webhook", b"{}")) is None
    assert v(body=b'{"x":1}') == "bad edge signature"          # body tampered
    assert v(path="/channels/whatsapp/webhook") == "bad edge signature"
    assert v(secret="other") == "bad edge signature"
    assert v(now=NOW + 61) == "stale edge timestamp"
    assert v(nonce="zz") == "bad edge nonce"
    assert v(sig=None) == "missing edge signature"
    assert v(secret=None) == "edge secret not configured"
    assert v() is None
    assert v() == "replayed edge request"                       # same nonce again


def test_nonce_cache_expires():
    n = edge.NonceCache(ttl=10)
    assert n.add("a" * 16, 0) and not n.add("a" * 16, 5)
    assert n.add("a" * 16, 11)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_worker_signature_verifies_in_python():
    js = ("import {edgeHeaders} from './worker.js';"
          "const b=new TextEncoder().encode('{\"update_id\":7}');"
          "console.log(JSON.stringify(await edgeHeaders({WITNESS_EDGE_SECRET:'shared'},'POST','/channels/telegram/webhook?a=1',b)))")
    d = os.path.join(ROOT, "deploy", "oracle", "cloudflare-worker")
    out = subprocess.run(["node", "--input-type=module", "-e", js], cwd=d, capture_output=True, text=True, check=True)
    h = json.loads(out.stdout)
    assert edge.verify("shared", h["x-witness-edge-ts"], h["x-witness-edge-nonce"], h["x-witness-edge-sig"], "POST",
                       "/channels/telegram/webhook?a=1", b'{"update_id":7}', nonces=edge.NonceCache(120)) is None


def guarded_app():
    app = FastAPI()
    edge.install(app)

    @app.post("/channels/telegram/webhook", dependencies=[Depends(edge.edge_guard)])
    async def hook(req: Request):
        return {"len": len(await req.body())}            # body still readable after the guard
    return app


def test_edge_guard_on_route(monkeypatch):
    monkeypatch.setenv("WITNESS_EDGE_SECRET", "s")
    monkeypatch.delenv("WITNESS_REQUIRE_EDGE", raising=False)
    c = TestClient(guarded_app())
    body = b'{"update_id":1}'
    ts, nonce, sig = signed("s", "POST", "/channels/telegram/webhook", body, ts=int(time.time()), nonce=os.urandom(16).hex())
    h = {"x-witness-edge-ts": ts, "x-witness-edge-nonce": nonce, "x-witness-edge-sig": sig}
    assert c.post("/channels/telegram/webhook", content=body, headers=h).json() == {"len": len(body)}
    assert c.post("/channels/telegram/webhook", content=body, headers=h).status_code == 401      # replay
    assert c.post("/channels/telegram/webhook", content=body).status_code == 401                 # direct-to-Space
    monkeypatch.delenv("WITNESS_EDGE_SECRET")
    assert c.post("/channels/telegram/webhook", content=body).status_code == 200                 # local dev: off
    monkeypatch.setenv("WITNESS_REQUIRE_EDGE", "true")
    assert c.post("/channels/telegram/webhook", content=body).status_code == 401                 # fail closed


def test_provider_signatures_still_checked_in_app(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "t")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "w")
    monkeypatch.setenv("IMESSAGE_WEBHOOK_SECRET", "bb")
    raw = b'{"entry":[]}'
    assert channels.telegram_verify("t") and not channels.telegram_verify("x") and not channels.telegram_verify(None)
    assert channels.whatsapp_verify_signature(raw, "sha256=" + hmac.new(b"w", raw, hashlib.sha256).hexdigest())
    assert not channels.whatsapp_verify_signature(raw + b" ", "sha256=" + hmac.new(b"w", raw, hashlib.sha256).hexdigest())
    assert channels.imessage_verify("bb") and not channels.imessage_verify("b")


def test_security_headers_and_strict_cors(monkeypatch):
    monkeypatch.setenv("WITNESS_COOKIE_SECURE", "true")
    monkeypatch.setenv("WITNESS_CORS_ORIGINS", "https://me-witness.hf.space, *")
    app = FastAPI()
    edge.install(app)

    @app.get("/api/v2/x")
    async def x():
        return {}
    c = TestClient(app)
    r = c.get("/api/v2/x", headers={"origin": "https://evil.example"})
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in r.headers                    # unknown origin, "*" ignored
    r = c.get("/api/v2/x", headers={"origin": "https://me-witness.hf.space"})
    assert r.headers["access-control-allow-origin"] == "https://me-witness.hf.space"
    assert edge.cors_origins() == ["https://me-witness.hf.space"]


def test_no_cors_by_default(monkeypatch):
    monkeypatch.delenv("WITNESS_CORS_ORIGINS", raising=False)
    monkeypatch.setenv("WITNESS_COOKIE_SECURE", "false")
    app = FastAPI()
    edge.install(app)
    app.get("/")(lambda: {})
    r = TestClient(app).get("/", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers and "strict-transport-security" not in r.headers


def test_per_sender_rate_limit():
    lim = RateLimiter(rate_per_min=0.0001, burst=3)
    assert [edge.sender_allowed("telegram", "42", lim) for _ in range(4)] == [True, True, True, False]
    assert edge.sender_allowed("telegram", "43", lim)          # other senders unaffected


def test_verify_full_tls(monkeypatch):
    monkeypatch.delenv("TIGER_DB_SSLMODE", raising=False)
    url, extra = tigerkit.tls_args("postgres://u:p@svc.prj.tsdb.cloud.timescale.com:31234/tsdb?sslmode=verify-full")
    import ssl
    ctx = extra["ssl"]
    assert "sslmode" not in url and ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert tigerkit.tls_args("postgres://u@localhost/db") == ("postgres://u@localhost/db", {})
    assert db_tls_problem("postgres://u:p@svc.tsdb.cloud.timescale.com:31234/tsdb?sslmode=require")
    assert not db_tls_problem("postgres://u:p@svc.tsdb.cloud.timescale.com:31234/tsdb?sslmode=verify-full")
    assert not db_tls_problem("postgres://u:p@localhost:5432/tsdb")
    monkeypatch.setenv("TIGER_DB_SSLMODE", "verify-full")
    assert not db_tls_problem("postgres://u:p@svc.tsdb.cloud.timescale.com:31234/tsdb?sslmode=require")


def test_prod_refuses_weak_db_tls(monkeypatch):
    from witness import config
    monkeypatch.setenv("WITNESS_ENV", "prod")
    monkeypatch.setenv("WITNESS_SIGNING_KEY", "x" * 40)
    monkeypatch.setenv("WITNESS_COOKIE_SECURE", "true")
    monkeypatch.delenv("TIGER_DB_SSLMODE", raising=False)
    monkeypatch.setenv("TIGER_DB_URL", "postgres://u:p@svc.tsdb.cloud.timescale.com:3/tsdb?sslmode=require")
    with pytest.raises(SystemExit, match="verify-full"):
        config.get_settings()
    monkeypatch.setenv("TIGER_DB_URL", "postgres://u:p@svc.tsdb.cloud.timescale.com:3/tsdb?sslmode=verify-full")
    assert config.get_settings().env == "prod"


# ------------------------------------------------------------------------------------------- streaming + routing
def sse(chunks, usage=50):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}" for c in chunks]
    lines.append(f"data: {json.dumps({'choices': [], 'usage': {'total_tokens': usage}})}")
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def mkr(handler, names=("groq", "cloudflare")):
    specs = [ProviderSpec(n, f"https://{n}.test/v1", "k", [Route(n, f"{n}-m", frozenset({"light", "main"}))])
             for n in names]
    calls = []

    def h(req):
        calls.append((req.url.host, json.loads(req.content)))
        return handler(req)
    return Router(specs, policy=BudgetPolicy(new_user_reserve=0), transport=httpx.MockTransport(h)), calls


async def collect(r, text):
    return [d async for d in r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": text}])]


async def test_stream_light_groq_first_and_think_stripped():
    r, calls = mkr(lambda req: httpx.Response(200, content=sse(["<think>hmm", "</think>Hi", " there"]),
                                              headers={"content-type": "text/event-stream"}))
    out = await collect(r, "tell me a fun fact about otters")
    assert "".join(out) == "Hi there" and len(out) == 2
    assert calls[0][0] == "groq.test" and calls[0][1]["stream"] is True
    assert r.stats["calls"] == 1
    assert await collect(r, "tell me a fun fact about otters") == ["Hi there"]   # exact cache: no 2nd call
    assert len(calls) == 1


async def test_stream_fails_over_before_first_token():
    def h(req):
        if req.url.host == "groq.test":
            return httpx.Response(429, headers={"retry-after": "30"}, json={})
        return httpx.Response(200, content=sse(["ok"]))
    r, calls = mkr(h)
    assert await collect(r, "what is a haiku") == ["ok"]
    assert [c[0] for c in calls] == ["groq.test", "cloudflare.test"]


async def test_stream_exhausted_raises():
    r, _ = mkr(lambda req: httpx.Response(503, json={}))
    with pytest.raises(R.QuotaExhausted):
        await collect(r, "what is a haiku")


def test_streamable_only_light_nonpersonal_firstturn():
    r, _ = mkr(lambda req: httpx.Response(200))
    assert r.streamable([{"role": "user", "content": "what is a haiku"}])
    assert not r.streamable([{"role": "user", "content": "pay my electric bill"}])
    assert not r.streamable([{"role": "user", "content": "x" * 500}])
    assert not r.streamable([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"},
                             {"role": "user", "content": "what is a haiku"}])


def test_light_tier_prefers_groq_from_env():
    specs = R.pool_from_env({"GROQ_API_KEY": "g", "CLOUDFLARE_API_TOKEN": "c", "CLOUDFLARE_ACCOUNT_ID": "a",
                             "OPENROUTER_API_KEY": "o", "WITNESS_LOCAL_LLM_URL": "http://127.0.0.1:8080/v1"})
    r = Router(specs, policy=BudgetPolicy(new_user_reserve=0))
    c = r.candidates("light", False)
    assert c[0][0].name == "groq" and c[-1][0].local
