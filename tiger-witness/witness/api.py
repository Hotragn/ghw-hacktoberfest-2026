"""Witness HTTP API + dashboard.  uvicorn witness.api:app --port 8103
Per-user accounts, server-side sessions (HttpOnly SameSite=Strict cookie or Bearer token), every query scoped
to the session's user_id. All execution is SIMULATED through witness.adapters."""
from __future__ import annotations
import json
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
import asyncpg
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import make_pool, text_embedding, vec_literal  # noqa: E402
from tigerprod import (RateLimiter, hash_password, install_http_hardening, log_event, new_token,  # noqa: E402
                       setup_logging, token_hash, verify_password)
from witness import agent  # noqa: E402
from witness.config import get_settings  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
S = get_settings()
setup_logging()
log = logging.getLogger("witness.api")
state: dict = {}
ACTIONS = ("pay_bill", "purchase", "book", "cancel_subscription", "disclose", "reply")


@asynccontextmanager
async def lifespan(_):
    state["pool"] = await make_pool("witness", max_size=int(os.environ.get("WITNESS_DB_POOL", "10")))
    log_event(log, "startup", env=S.env, adapters=S.adapters)
    yield
    await state["pool"].close()

app = FastAPI(title="Witness - the personal agent that can prove it", version="2.0.0", lifespan=lifespan)
install_http_hardening(app, "witness", RateLimiter(S.rate_per_min, S.rate_burst))
login_limiter = RateLimiter(float(os.environ.get("WITNESS_LOGIN_RATE_PER_MIN", "10")),
                            int(os.environ.get("WITNESS_LOGIN_BURST", "5")))  # brute-force guard per IP on auth endpoints


def pool() -> asyncpg.Pool:
    return state["pool"]


# ------------------------------------------------------------------ models (validation)
class Register(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    home_channel: Literal["sms", "whatsapp", "imessage", "slack", "teams", "telegram"] = "sms"

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("invalid email")
        return v.lower()


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AgentRequest(BaseModel):
    text: str = Field(min_length=3, max_length=500)


class Inbound(BaseModel):
    channel: Literal["sms", "whatsapp", "imessage", "slack", "teams", "telegram", "email"]
    sender: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=3, max_length=2000)


class MandateIn(BaseModel):
    kind: Literal["one_time", "standing"]
    action: Literal["pay_bill", "purchase", "book", "cancel_subscription", "disclose", "reply"]
    counterparty: str = Field(default="*", min_length=1, max_length=80, pattern=r"^[\w\s\*\.\:\-']+$")
    max_amount: float | None = Field(default=None, ge=0, le=100000)
    monthly_cap: float | None = Field(default=None, ge=0, le=1000000)
    disclose: list[Literal["address", "health", "financial", "personal"]] = []
    uses_left: int | None = Field(default=None, ge=1, le=1000)
    daily_action_budget: int | None = Field(default=None, ge=1, le=1000)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    note: str | None = Field(default=None, max_length=200)


class ReplayIn(BaseModel):
    since_days: int = Field(default=30, ge=1, le=365)
    params: dict[str, float] | None = None
    mandate_patch: list[dict] | None = Field(default=None, max_length=50)

    @field_validator("params")
    @classmethod
    def _params(cls, v):
        allowed = {"min_tool_reputation", "scam_block", "anomaly_multiplier"}
        if v and not set(v) <= allowed:
            raise ValueError(f"params must be among {sorted(allowed)}")
        return v


# ------------------------------------------------------------------ auth
async def current_user(authorization: str | None = Header(default=None),
                       witness_session: str | None = Cookie(default=None)) -> str:
    tok = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else witness_session
    if not tok or len(tok) > 200:
        raise HTTPException(401, "not authenticated", headers={"WWW-Authenticate": "Bearer"})
    h = token_hash(tok)
    uid = await pool().fetchval("SELECT user_id FROM sessions WHERE token_sha256=$1 AND expires_at > now()", h)
    if not uid and tok.startswith("wit_pat_"):  # personal API token (RLS: looked up under the system context)
        from witness.db import system_tx
        async with system_tx(pool()) as c:
            uid = await c.fetchval("""UPDATE api_tokens SET last_used_at=now() WHERE token_sha256=$1 AND revoked_at IS NULL
                AND expires_at > now() RETURNING user_id""", h)
    if not uid:
        raise HTTPException(401, "session expired or invalid", headers={"WWW-Authenticate": "Bearer"})
    return uid


def _client(req: Request) -> str:
    return req.client.host if req.client else "unknown"


async def _issue_session(uid: str, req: Request, resp: Response) -> dict:
    tok, h = new_token()
    exp = datetime.now(timezone.utc) + timedelta(hours=S.session_ttl_hours)
    await pool().execute("INSERT INTO sessions (token_sha256,user_id,expires_at,ip,user_agent) VALUES ($1,$2,$3,$4,$5)",
                         h, uid, exp, _client(req), (req.headers.get("user-agent") or "")[:200])
    resp.set_cookie("witness_session", tok, httponly=True, samesite="strict", secure=S.cookie_secure,
                    max_age=S.session_ttl_hours * 3600, path="/")
    return {"user_id": uid, "token": tok, "expires_at": exp.isoformat()}


@app.post("/api/auth/register", status_code=201)
async def register(body: Register, req: Request, resp: Response):
    if not S.allow_registration:
        raise HTTPException(403, "registration disabled")
    if not login_limiter.allow("reg:" + _client(req)):
        raise HTTPException(429, "too many attempts")
    uid = "u-" + uuid.uuid4().hex[:12]
    async with pool().acquire() as c:
        async with c.transaction():
            if await c.fetchval("SELECT 1 FROM accounts WHERE lower(email)=$1", body.email):
                raise HTTPException(409, "email already registered")
            await c.execute("INSERT INTO users (user_id, display_name, home_channel) VALUES ($1,$2,$3)",
                            uid, body.display_name, body.home_channel)
            await c.execute("INSERT INTO accounts (user_id,email,pw_hash) VALUES ($1,$2,$3)",
                            uid, body.email, hash_password(body.password))
    log_event(log, "registered", user_id=uid)
    return await _issue_session(uid, req, resp)


@app.post("/api/auth/login")
async def login(body: Login, req: Request, resp: Response):
    if not login_limiter.allow("login:" + _client(req)):
        raise HTTPException(429, "too many attempts")
    a = await pool().fetchrow("SELECT user_id, pw_hash, locked_until FROM accounts WHERE lower(email)=lower($1)", body.email)
    if a and a["locked_until"] and a["locked_until"] > datetime.now(timezone.utc):
        raise HTTPException(423, "account temporarily locked")
    if not a or not verify_password(body.password, a["pw_hash"]):
        if a:
            await pool().execute("""UPDATE accounts SET failed_logins = failed_logins + 1,
                locked_until = CASE WHEN failed_logins + 1 >= 5 THEN now() + interval '15 minutes' END WHERE user_id=$1""",
                a["user_id"])
        log_event(log, "login_failed", level=logging.WARNING)
        raise HTTPException(401, "invalid email or password")
    await pool().execute("UPDATE accounts SET failed_logins=0, locked_until=NULL WHERE user_id=$1", a["user_id"])
    return await _issue_session(a["user_id"], req, resp)


@app.post("/api/auth/logout")
async def logout(resp: Response, authorization: str | None = Header(default=None),
                 witness_session: str | None = Cookie(default=None)):
    tok = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else witness_session
    if tok:
        await pool().execute("DELETE FROM sessions WHERE token_sha256=$1", token_hash(tok))
    resp.delete_cookie("witness_session", path="/")
    return {"ok": True}


# ------------------------------------------------------------------ health
@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    try:
        await pool().fetchval("SELECT 1")
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "database unavailable") from None
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


# ------------------------------------------------------------------ agent
def _rows(rs, jsonf=("intent", "reasons", "assumptions", "payload")):
    out = []
    for r in rs:
        d = dict(r)
        for k in jsonf:
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
        out.append(d)
    return out


@app.get("/api/me")
async def me(uid: str = Depends(current_user)):
    return dict(await pool().fetchrow("""SELECT u.user_id, u.display_name, u.home_channel, a.email FROM users u
        JOIN accounts a USING (user_id) WHERE u.user_id=$1""", uid))


@app.post("/api/requests")
async def make_request(body: AgentRequest, uid: str = Depends(current_user)):
    try:
        return await agent.handle(pool(), uid, body.text)
    except agent.AgentError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/inbound")
async def inbound(body: Inbound, uid: str = Depends(current_user)):
    return await agent.handle_inbound(pool(), uid, body.channel, body.sender, body.body)


@app.get("/api/actions")
async def actions(limit: int = 50, uid: str = Depends(current_user)):
    limit = max(1, min(limit, 500))
    return _rows(await pool().fetch("""SELECT a.ts, a.action_id, a.request, a.source, a.intent, a.decision, a.reasons,
        a.assumptions, a.evidence, a.mandate_id, a.tool_id, a.merchant, a.amount, p.outcome AS approval
        FROM actions a LEFT JOIN approvals p USING (action_id) WHERE a.user_id=$1 ORDER BY a.ts DESC LIMIT $2""", uid, limit))


@app.post("/api/actions/{action_id}/{verb}")
async def decide(action_id: uuid.UUID, verb: Literal["approve", "deny"], uid: str = Depends(current_user)):
    try:
        return await agent.decide(pool(), uid, str(action_id), verb == "approve")
    except agent.AgentError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/receipts")
async def receipts(limit: int = 50, uid: str = Depends(current_user)):
    return _rows(await pool().fetch("""SELECT seq, ts, action_id, payload, prev_hash, hash, signature FROM receipts
        WHERE user_id=$1 ORDER BY seq DESC LIMIT $2""", uid, max(1, min(limit, 500))))


@app.get("/api/receipts/verify")
async def verify(uid: str = Depends(current_user)):
    return await agent.verify(pool(), uid)


@app.get("/api/evidence/{event_id}")
async def evidence(event_id: int, uid: str = Depends(current_user)):
    r = await pool().fetchrow("SELECT ts, event_id, kind, merchant, category, amount, simulated, detail FROM life_events WHERE event_id=$1 AND user_id=$2", event_id, uid)
    if not r:
        raise HTTPException(404, "not found")
    return dict(r)


@app.get("/api/mandates")
async def mandates(uid: str = Depends(current_user)):
    return [dict(r) for r in await pool().fetch("SELECT * FROM mandates WHERE user_id=$1 ORDER BY revoked_at NULLS FIRST, created_at", uid)]


@app.post("/api/mandates", status_code=201)
async def add_mandate(m: MandateIn, uid: str = Depends(current_user)):
    mid = "m-" + uuid.uuid4().hex[:10]
    exp = datetime.now(timezone.utc) + timedelta(days=m.expires_in_days) if m.expires_in_days else None
    await pool().execute("""INSERT INTO mandates (mandate_id,user_id,kind,action,counterparty,max_amount,monthly_cap,disclose,
        uses_left,daily_action_budget,expires_at,note) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
        mid, uid, m.kind, m.action, m.counterparty.lower(), m.max_amount, m.monthly_cap, m.disclose, m.uses_left,
        m.daily_action_budget, exp, m.note)
    log_event(log, "mandate_created", user_id=uid, mandate_id=mid, action=m.action)
    return {"mandate_id": mid}


@app.post("/api/mandates/{mandate_id}/revoke")
async def revoke(mandate_id: str, uid: str = Depends(current_user)):
    r = await pool().execute("UPDATE mandates SET revoked_at=now() WHERE mandate_id=$1 AND user_id=$2 AND revoked_at IS NULL", mandate_id, uid)
    if r.endswith(" 0"):
        raise HTTPException(404, "no active mandate with that id")
    return {"ok": True}


@app.get("/api/insights")
async def insights(uid: str = Depends(current_user)):
    p = pool()
    return {"subscription_creep": [dict(r) for r in await p.fetch("SELECT * FROM subscription_creep($1)", uid)],
            "idle_subscriptions": [dict(r) for r in await p.fetch("SELECT * FROM idle_subscriptions($1)", uid)],
            "consent_drift": [dict(r) for r in await p.fetch("SELECT * FROM consent_drift($1)", uid)],
            "monthly_spend": [dict(r) for r in await p.fetch("""SELECT bucket, sum(total) AS total FROM spend_monthly
                WHERE user_id=$1 GROUP BY 1 ORDER BY 1""", uid)],
            "decisions_7d": [dict(r) for r in await p.fetch("""SELECT decision, sum(n)::int AS n FROM actions_hourly
                WHERE user_id=$1 AND bucket > now() - interval '7 days' GROUP BY 1""", uid)]}


@app.get("/api/recall")
async def recall(q: str, kind: str | None = None, uid: str = Depends(current_user)):
    if not 1 <= len(q) <= 200:
        raise HTTPException(422, "q must be 1..200 chars")
    rs = await pool().fetch("SELECT * FROM recall($1,$2::vector,$3,NULL,'400 days',5)", uid,
                            vec_literal(text_embedding(q)), [kind] if kind else None)
    return [dict(r) for r in rs]


@app.post("/api/replay")
async def replay(body: ReplayIn, uid: str = Depends(current_user)):
    for pm in body.mandate_patch or []:
        if not isinstance(pm.get("mandate_id"), str):
            raise HTTPException(422, "each mandate_patch item needs a mandate_id")
        pm["user_id"] = uid
        if "action" in pm and pm["action"] not in ACTIONS:
            raise HTTPException(422, "bad action in mandate_patch")
    return await agent.replay(pool(), uid, body.since_days, body.params, body.mandate_patch)


# ------------------------------------------------------------------ v2: task-executing agent
from witness import api_v2  # noqa: E402
api_v2.install(app, pool, current_user, state)


@app.get("/app")
async def app_ui():
    return FileResponse(os.path.join(STATIC, "app.html"))
