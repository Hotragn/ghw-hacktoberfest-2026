"""v2 HTTP API: chat with the agent, approvals inbox, memory, grants, payment mandates, receipts timeline,
API tokens, MCP servers, connectors, and channel webhooks (Telegram, WhatsApp, iMessage relay, signed webhook)."""
from __future__ import annotations
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from tigerprod import token_hash
from witness import channels, consent, edge, jobs, llm, memory, passkeys, payments
from witness.db import user_tx
from witness.runtime import Agent
from witness.tools import Services


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class DecideIn(BaseModel):
    approve: bool
    challenge_id: str | None = None
    credential: dict | None = None


class PasskeyFinish(BaseModel):
    challenge_id: str
    credential: dict
    name: str = Field(default="passkey", max_length=60)


class AssertionIn(BaseModel):
    challenge_id: str
    credential: dict


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["fact", "preference", "person", "place", "episode"] = "fact"


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    pinned: bool | None = None
    kind: Literal["fact", "preference", "person", "place", "episode"] | None = None


class GrantIn(BaseModel):
    tool_pattern: str = Field(min_length=1, max_length=120, pattern=r"^[\w:/*?.\-]+$")
    scopes: list[Literal["read", "write"]] = ["read"]
    data_classes: list[Literal["public", "personal", "financial", "address", "health"]] = ["public", "personal"]
    ttl_hours: float = Field(default=24, gt=0, le=8760)
    auto_approve: bool = False
    max_uses: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=200)


class PayMandateIn(BaseModel):
    description: str = Field(min_length=3, max_length=300)
    merchants: list[str] = Field(min_length=1, max_length=50)
    max_per_txn: float = Field(gt=0, le=100000)
    budget: float = Field(gt=0, le=1000000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    ttl_days: float = Field(default=30, gt=0, le=365)
    window_days: int = Field(default=30, ge=1, le=365)
    human_present_required: bool = False


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    ttl_days: int = Field(default=90, ge=1, le=365)


class McpIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    transport: Literal["http", "stdio"] = "http"
    target: str = Field(min_length=3, max_length=500)
    auth_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")


class ConnectorIn(BaseModel):
    kind: Literal["ics", "caldav", "imap", "smtp"]
    config: dict


class LinkIn(BaseModel):
    channel: Literal["telegram", "whatsapp", "imessage"]


def _j(v):
    if isinstance(v, (datetime,)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


STREAM_SYSTEM = ("You are Witness, a concise personal assistant. Answer briefly. You cannot take actions in this "
                 "reply; if asked to do something, say you will handle it as a task.")  # byte-stable: prompt-cache prefix


def install(app, pool, current_user, state: dict):
    r = APIRouter(prefix="/api/v2")

    def agent() -> Agent:
        if "agent" not in state:
            state["agent"] = Agent(pool(), state.get("provider") or llm.from_env(pool=pool()), state.get("services") or Services())
        a = state["agent"]
        a.pool = pool()
        return a

    def senders() -> dict:
        if "senders" not in state:
            state["senders"] = channels.senders_from_env()
        return state["senders"]

    # ---- chat + tasks
    @r.post("/chat")
    async def chat(body: ChatIn, uid: str = Depends(current_user)):
        from witness import deferral
        from witness.router import QuotaExhausted
        try:
            return await agent().run(uid, body.message, channel="web")
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except QuotaExhausted as q:  # every free provider is out: park durably, answer when quota resets
            when, _ = await deferral.defer_turn(pool(), uid, {"channel": "web", "text": body.message}, q.retry_at)
            return {"task_id": None, "status": "deferred", "reply": deferral.saved_message(when), "retry_at": when,
                    "steps": [], "approval_id": None}

    @r.post("/chat/stream")
    async def chat_stream(body: ChatIn, uid: str = Depends(current_user)):
        """Server-sent events. Light, first-turn, non-personal, tool-free messages stream token by token straight
        from the router (Groq first). Everything else runs the normal agent (tools, taint/consent gating, passkeys
        unchanged) and arrives as one `final` event with the same JSON as POST /chat."""
        from witness import router as rt
        a = agent()
        prov = a.provider
        msgs = [{"role": "system", "content": STREAM_SYSTEM}, {"role": "user", "content": body.message}]

        def ev(name, data):
            return f"event: {name}\ndata: {json.dumps(data)}\n\n"

        async def gen():
            tok = rt.CTX.set({"user": uid})   # set inside the generator: it runs in the response's own context
            try:
                if isinstance(prov, rt.Router) and prov.streamable(msgs[1:], {"user": uid}):
                    try:
                        async for d in prov.stream(msgs):
                            yield ev("delta", {"text": d})
                        yield ev("done", {})
                        return
                    except rt.QuotaExhausted:
                        pass   # fall through to the agent, which defers durably
                yield ev("final", await chat(body, uid))
            finally:
                rt.CTX.reset(tok)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no"})

    @r.get("/tasks")
    async def tasks(limit: int = Query(30, ge=1, le=200), uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            rs = await c.fetch("""SELECT task_id, channel, lang, goal, status, steps, tainted, result, created_at, updated_at
                FROM agent_tasks WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2""", uid, limit)
        return [{k: _j(v) for k, v in dict(x).items()} for x in rs]

    @r.get("/tasks/{task_id}/events")
    async def task_events(task_id: uuid.UUID, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            rs = await c.fetch("SELECT ts, kind, tool, tainted, content FROM my_agent_events WHERE task_id=$1 ORDER BY ts, event_id", task_id)
        return [{"ts": x["ts"].isoformat(), "kind": x["kind"], "tool": x["tool"], "tainted": x["tainted"],
                 "content": json.loads(x["content"])} for x in rs]

    # ---- approvals inbox
    @r.get("/approvals")
    async def approvals(status: Literal["pending", "approved", "denied", "expired", "all"] = "pending",
                        uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await consent.list_approvals(c, uid, None if status == "all" else status)

    @r.post("/approvals/{approval_id}/passkey-options")
    async def approval_passkey_options(approval_id: uuid.UUID, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            a = await consent.get_pending(c, uid, str(approval_id))
            if not a:
                raise HTTPException(404, "no pending approval")
            try:
                return await passkeys.begin_assertion(c, uid, "approval", str(approval_id), consent.approval_sha256(a))
            except passkeys.PasskeyError as e:
                raise HTTPException(409, str(e)) from None

    @r.post("/approvals/{approval_id}")
    async def decide(approval_id: uuid.UUID, body: DecideIn, uid: str = Depends(current_user)):
        evidence = None
        if body.approve and body.credential:
            async with user_tx(pool(), uid) as c:
                a = await consent.get_pending(c, uid, str(approval_id))
                if not a:
                    raise HTTPException(409, "no pending approval")
                try:
                    evidence = await passkeys.finish_assertion(c, uid, body.challenge_id or "", body.credential, "approval",
                                                               str(approval_id), consent.approval_sha256(a))
                except (passkeys.PasskeyError, ValueError) as e:
                    raise HTTPException(401, str(e)) from None
        try:
            return await agent().decide(uid, str(approval_id), body.approve, evidence)
        except passkeys.PasskeyRequired as e:
            raise HTTPException(428, str(e)) from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    # ---- passkeys (WebAuthn)
    @r.get("/passkeys")
    async def pk_list(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await passkeys.list_passkeys(c, uid)

    @r.post("/passkeys/register/options")
    async def pk_reg_options(uid: str = Depends(current_user)):
        email = await pool().fetchval("SELECT email FROM accounts WHERE user_id=$1", uid) or uid
        async with user_tx(pool(), uid) as c:
            return await passkeys.begin_registration(c, uid, email, email)

    @r.post("/passkeys/register/verify", status_code=201)
    async def pk_reg_verify(body: PasskeyFinish, uid: str = Depends(current_user)):
        try:
            async with user_tx(pool(), uid) as c:
                return await passkeys.finish_registration(c, uid, body.challenge_id, body.credential, body.name)
        except (passkeys.PasskeyError, ValueError) as e:
            raise HTTPException(400, str(e)) from None

    # ---- memory
    @r.get("/memory")
    async def mem_list(q: str | None = Query(None, max_length=200), uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await (memory.search(c, uid, q, 20) if q else memory.list_items(c, uid))

    @r.post("/memory", status_code=201)
    async def mem_add(body: MemoryIn, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await memory.add(c, uid, body.text, body.kind, source="user")

    @r.patch("/memory/{memory_id}")
    async def mem_edit(memory_id: int, body: MemoryPatch, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            m = await memory.edit(c, uid, memory_id, body.text, body.pinned, body.kind)
        if not m:
            raise HTTPException(404, "no such memory")
        return m

    @r.delete("/memory/{memory_id}")
    async def mem_forget(memory_id: int, uid: str = Depends(current_user)):
        from witness.agent import append_receipt
        async with user_tx(pool(), uid) as c:
            h = await memory.forget(c, uid, memory_id)
            if not h:
                raise HTTPException(404, "no such memory")
            rc = await append_receipt(c, uid, uuid.uuid4(), datetime.now(timezone.utc),
                                      {"kind": "memory_forgotten", "memory_id": memory_id, "text_sha256": h})
        return {"forgotten": memory_id, "text_sha256": h, "receipt": rc}

    @r.get("/habits")
    async def habits(days: int = Query(30, ge=1, le=365), uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await memory.habits(c, uid, days)

    # ---- grants
    @r.get("/grants")
    async def grants(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await consent.list_grants(c, uid)

    @r.post("/grants", status_code=201)
    async def grant_add(body: GrantIn, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await consent.create_grant(c, uid, body.tool_pattern, list(body.scopes), list(body.data_classes),
                                              body.ttl_hours, body.auto_approve, body.max_uses, body.note)

    @r.post("/grants/{grant_id}/revoke")
    async def grant_revoke(grant_id: uuid.UUID, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            if not await consent.revoke_grant(c, uid, str(grant_id)):
                raise HTTPException(404, "no active grant with that id")
        return {"revoked": str(grant_id)}

    # ---- payment mandates
    @r.get("/payment-mandates")
    async def pms(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            return await payments.list_mandates(c, uid)

    @r.post("/payment-mandates", status_code=201)
    async def pm_add(body: PayMandateIn, uid: str = Depends(current_user)):
        try:
            async with user_tx(pool(), uid) as c:
                need = await passkeys.has_passkey(c, uid) or os.environ.get("WITNESS_REQUIRE_PASSKEY", "false").lower() == "true"
                m = await payments.create_open_mandate(c, uid, body.description, body.merchants, body.max_per_txn,
                                                       body.budget, body.ttl_days, body.currency, body.window_days,
                                                       body.human_present_required, passkey_required=need)
                if need:  # the mandate is inactive until the user signs its hash with a passkey
                    try:
                        m["passkey_challenge"] = await passkeys.begin_assertion(c, uid, "mandate", m["mandate_id"],
                                                                                payments.mandate_sha256(m["content"]))
                    except passkeys.PasskeyError:
                        m["passkey_challenge"] = None  # required by env but no passkey yet: register one, then /confirm-options
                return m
        except payments.PaymentError as e:
            raise HTTPException(422, str(e)) from None

    @r.post("/payment-mandates/{mandate_id}/confirm-options")
    async def pm_confirm_options(mandate_id: str, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            row = await c.fetchrow("SELECT content FROM pay_mandates WHERE mandate_id=$1 AND user_id=$2 AND revoked_at IS NULL",
                                   mandate_id, uid)
            if not row:
                raise HTTPException(404, "no active mandate")
            try:
                return await passkeys.begin_assertion(c, uid, "mandate", mandate_id, payments.mandate_sha256(json.loads(row["content"])))
            except passkeys.PasskeyError as e:
                raise HTTPException(409, str(e)) from None

    @r.post("/payment-mandates/{mandate_id}/confirm")
    async def pm_confirm(mandate_id: str, body: AssertionIn, uid: str = Depends(current_user)):
        try:
            async with user_tx(pool(), uid) as c:
                row = await c.fetchrow("SELECT content FROM pay_mandates WHERE mandate_id=$1 AND user_id=$2", mandate_id, uid)
                if not row:
                    raise HTTPException(404, "no such mandate")
                ev = await passkeys.finish_assertion(c, uid, body.challenge_id, body.credential, "mandate", mandate_id,
                                                     payments.mandate_sha256(json.loads(row["content"])))
                m = await payments.confirm_with_passkey(c, uid, mandate_id, ev)
                m["passkey_evidence_valid"] = passkeys.verify_evidence(ev)
                return m
        except (passkeys.PasskeyError, payments.PaymentError) as e:
            raise HTTPException(401, str(e)) from None

    @r.post("/payment-mandates/{mandate_id}/revoke")
    async def pm_revoke(mandate_id: str, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            if not await payments.revoke_mandate(c, uid, mandate_id):
                raise HTTPException(404, "no active mandate with that id")
        return {"revoked": mandate_id}

    @r.get("/payments")
    async def pay_list(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            rs = await c.fetch("SELECT * FROM payments WHERE user_id=$1 ORDER BY ts DESC LIMIT 100", uid)
        out = [payments._row(x) for x in rs]
        for p in out:
            p["agent_signature_valid"] = payments.agent_verify(p["closed_mandate"], p["agent_signature"])
        return out

    @r.get("/agent-key")
    async def agent_key():
        return {"alg": "ES256", "public_key_pem": payments.agent_public_pem()}

    # ---- receipts timeline (unified hash chain shared with v1)
    @r.get("/timeline")
    async def timeline(limit: int = Query(100, ge=1, le=500), uid: str = Depends(current_user)):
        rs = await pool().fetch("""SELECT seq, ts, payload, hash, prev_hash FROM receipts WHERE user_id=$1
            ORDER BY seq DESC LIMIT $2""", uid, limit)
        return [{"seq": x["seq"], "ts": x["ts"].isoformat(), "hash": x["hash"], "prev_hash": x["prev_hash"],
                 "payload": json.loads(x["payload"])} for x in rs]

    # ---- API tokens
    @r.get("/tokens")
    async def tokens(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            rs = await c.fetch("""SELECT left(token_sha256,12) AS id, name, scopes, created_at, expires_at, revoked_at, last_used_at
                FROM api_tokens WHERE user_id=$1 ORDER BY created_at DESC""", uid)
        return [{k: _j(v) for k, v in dict(x).items()} for x in rs]

    @r.post("/tokens", status_code=201)
    async def token_add(body: TokenIn, uid: str = Depends(current_user)):
        tok = "wit_pat_" + secrets.token_urlsafe(32)
        exp = datetime.now(timezone.utc) + timedelta(days=body.ttl_days)
        async with user_tx(pool(), uid) as c:
            await c.execute("INSERT INTO api_tokens (token_sha256,user_id,name,expires_at) VALUES ($1,$2,$3,$4)",
                            token_hash(tok), uid, body.name, exp)
        return {"token": tok, "id": token_hash(tok)[:12], "expires_at": exp.isoformat(), "note": "shown once"}

    @r.delete("/tokens/{token_id}")
    async def token_revoke(token_id: str, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            ok = await c.fetchval("""UPDATE api_tokens SET revoked_at=now() WHERE user_id=$1 AND left(token_sha256,12)=$2
                AND revoked_at IS NULL RETURNING 1""", uid, token_id)
        if not ok:
            raise HTTPException(404, "no such token")
        return {"revoked": token_id}

    # ---- MCP servers + connectors
    @r.get("/mcp-servers")
    async def mcp_list(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            rs = await c.fetch("SELECT server_id, name, transport, target, auth_env, created_at FROM mcp_servers WHERE user_id=$1", uid)
        return [{k: _j(v) for k, v in dict(x).items()} for x in rs]

    @r.post("/mcp-servers", status_code=201)
    async def mcp_add(body: McpIn, uid: str = Depends(current_user)):
        if body.transport == "http" and not body.target.startswith("https://"):
            raise HTTPException(422, "http transport requires an https:// URL")
        async with user_tx(pool(), uid) as c:
            sid = await c.fetchval("""INSERT INTO mcp_servers (server_id,user_id,name,transport,target,auth_env)
                VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (user_id,name) DO UPDATE SET target=EXCLUDED.target,
                transport=EXCLUDED.transport, auth_env=EXCLUDED.auth_env RETURNING server_id""",
                uuid.uuid4(), uid, body.name, body.transport, body.target, body.auth_env)
        return {"server_id": str(sid), "name": body.name}

    @r.delete("/mcp-servers/{name}")
    async def mcp_del(name: str, uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            await c.execute("DELETE FROM mcp_servers WHERE user_id=$1 AND name=$2", uid, name)
        return {"deleted": name}

    @r.put("/connectors")
    async def connector_put(body: ConnectorIn, uid: str = Depends(current_user)):
        bad = [k for k in body.config if k.lower() in ("password", "secret", "token", "api_key")]
        if bad:
            raise HTTPException(422, "never store secrets here; put them in an env var and set secret_env")
        async with user_tx(pool(), uid) as c:
            await c.execute("""INSERT INTO connectors (user_id,kind,config) VALUES ($1,$2,$3::jsonb)
                ON CONFLICT (user_id,kind) DO UPDATE SET config=EXCLUDED.config, updated_at=now()""",
                            uid, body.kind, json.dumps(body.config))
        return {"ok": True}

    # ---- channels (linking + per-user webhook secret)
    @r.post("/channels/link-code")
    async def link_code(body: LinkIn, uid: str = Depends(current_user)):
        return {"code": await channels.new_link_code(pool(), uid, body.channel), "expires_in_s": 900,
                "send": "link <CODE> (Telegram: /start <CODE>)"}

    @r.get("/channels")
    async def channel_list(uid: str = Depends(current_user)):
        async with user_tx(pool(), uid) as c:
            rs = await c.fetch("SELECT channel, external_id, linked_at FROM channel_links WHERE user_id=$1", uid)
        return {"links": [{k: _j(v) for k, v in dict(x).items()} for x in rs],
                "webhook": {"url": "/channels/webhook", "user": uid, "secret": channels.webhook_secret(uid),
                            "signature": "hex hmac_sha256(secret, X-Witness-Timestamp + '.' + body)"}}

    app.include_router(r)

    # ---- public channel webhooks (authenticated by channel-specific signatures, never by session)
    async def _route(inbs, background: BackgroundTasks, channel: str):
        """Durable hand-off: persist to the job queue and ACK immediately; witness.worker processes it."""
        async with pool().acquire() as c:
            for inb in inbs:
                if not edge.sender_allowed(inb.channel, inb.external_id):  # per chat id/phone, not per (edge) IP
                    continue                                           # 200 anyway: a 429 only makes providers retry
                payload, key = inb.job()
                await jobs.enqueue(c, "channel", payload, key)

    @app.post("/channels/telegram/webhook", dependencies=[Depends(edge.edge_guard)])
    async def tg_hook(req: Request, background: BackgroundTasks,
                      x_telegram_bot_api_secret_token: str | None = Header(default=None)):
        if not channels.telegram_verify(x_telegram_bot_api_secret_token):
            raise HTTPException(401, "bad secret")
        inb = channels.telegram_parse(await req.json())
        await _route([inb] if inb else [], background, "telegram")
        return {"ok": True}

    @app.get("/channels/whatsapp/webhook", dependencies=[Depends(edge.edge_guard)])
    async def wa_verify(mode: str | None = Query(None, alias="hub.mode"), token: str | None = Query(None, alias="hub.verify_token"),
                        challenge: str | None = Query(None, alias="hub.challenge")):
        ch = channels.whatsapp_verify_challenge(mode, token, challenge)
        if ch is None:
            raise HTTPException(403, "verification failed")
        return PlainTextResponse(ch)

    @app.post("/channels/whatsapp/webhook", dependencies=[Depends(edge.edge_guard)])
    async def wa_hook(req: Request, background: BackgroundTasks, x_hub_signature_256: str | None = Header(default=None)):
        raw = await req.body()
        if not channels.whatsapp_verify_signature(raw, x_hub_signature_256):
            raise HTTPException(401, "bad signature")
        await _route(channels.whatsapp_parse(json.loads(raw)), background, "whatsapp")
        return {"ok": True}

    @app.post("/channels/imessage/webhook", dependencies=[Depends(edge.edge_guard)])
    async def im_hook(req: Request, background: BackgroundTasks, token: str | None = Query(None)):
        if not channels.imessage_verify(token):
            raise HTTPException(401, "bad token")
        inb = channels.imessage_parse(await req.json())
        await _route([inb] if inb else [], background, "imessage")
        return {"ok": True}

    @app.post("/channels/webhook")
    async def generic_hook(req: Request, x_witness_user: str = Header(...), x_witness_timestamp: str | None = Header(default=None),
                           x_witness_signature: str | None = Header(default=None)):
        raw = await req.body()
        if not channels.webhook_verify(x_witness_user, x_witness_timestamp, x_witness_signature, raw):
            raise HTTPException(401, "bad signature or stale timestamp")
        body = json.loads(raw)
        text = str(body.get("text", ""))[:4000]
        if body.get("approval_id"):
            res = await agent().decide(x_witness_user, str(body["approval_id"]), bool(body.get("approve")))
        else:
            res = await agent().run(x_witness_user, text, channel="webhook")
        return res
