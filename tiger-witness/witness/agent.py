"""Witness agent core: plan -> gather evidence -> freeze context -> policy -> (simulated) act -> signed receipt.
Nothing here touches a real account. Execution writes a SIMULATED life_event and a receipt; that's it."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import load_env, text_embedding, vec_literal  # noqa: E402
from witness.policy import evaluate, POLICY_VERSION  # noqa: E402
from witness import adapters as adp  # noqa: E402

ADAPTERS = adp.registry(os.environ.get("WITNESS_ADAPTERS", "sim"))


class AgentError(ValueError):
    """Bad input to the agent (surfaced as HTTP 400)."""

TOOL_FOR = {"pay_bill": "billpay.plaid-sim", "purchase": "checkout.ap2-sim", "book": "reserve.opentable-sim",
            "cancel_subscription": "subs.cancel-sim", "disclose": "marketplace.reply-sim", "reply": "marketplace.reply-sim"}
SCAM_HINTS = ["gift card", "wire", "urgent", "arrest", "irs", "warrant", "crypto", "bitcoin", "verify your account",
              "suspended", "refund", "act now", "do not tell"]


def signing_key() -> bytes:
    load_env()
    k = os.environ.get("WITNESS_SIGNING_KEY")
    if not k:
        raise RuntimeError("WITNESS_SIGNING_KEY is not set")
    return k.encode()


def sign(h: str) -> str:
    return hmac.new(signing_key(), h.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- planner
def parse(text: str) -> dict:
    """Deterministic intent parser (swap in an LLM planner that must emit this same JSON shape)."""
    t = text.lower().strip()
    amt = re.search(r"\$\s?(\d+(?:\.\d{1,2})?)", t)
    amount = float(amt.group(1)) if amt else None
    if m := re.search(r"(?:pay|settle)\s+(?:my\s+|the\s+)?(.+?)\s+bill", t):
        return {"action": "pay_bill", "merchant_hint": m.group(1), "amount": amount}
    if m := re.search(r"pay\s+\$?[\d.]+\s+(?:in\s+)?(gift cards?|bitcoin|crypto|wire)\s*(?:to\s+(.+))?", t):
        return {"action": "purchase", "merchant_hint": (m.group(2) or m.group(1)).strip(" ."), "amount": amount,
                "item": m.group(1)}
    if m := re.search(r"cancel\s+(?:my\s+)?(.+?)(?:\s+subscription|\s+membership)?$", t):
        return {"action": "cancel_subscription", "merchant_hint": m.group(1).strip(" ."), "amount": 0}
    if m := re.search(r"(?:buy|order|reorder)\s+(.+?)\s+from\s+(.+?)(?:\s+for|\s*$)", t):
        return {"action": "purchase", "merchant_hint": m.group(2).strip(" ."), "amount": amount, "item": m.group(1)}
    if m := re.search(r"book\s+(.+?)\s+at\s+(.+?)(?:\s+for|\s*$)", t):
        return {"action": "book", "merchant_hint": m.group(2).strip(" ."), "amount": amount, "item": m.group(1)}
    if m := re.search(r"(?:reply to|answer)\s+(?:the\s+)?(?:marketplace\s+)?(?:buyer\s+)?(\w+)(.*)", t):
        disclose = ["address"] if re.search(r"address|pick ?up at|come to", t) else []
        return {"action": "disclose" if disclose else "reply", "merchant_hint": f"marketplace:{m.group(1)}",
                "amount": amount, "disclose": disclose}
    if m := re.search(r"(?:send|share|give)\s+(?:my\s+)?(home\s+)?address\s+(?:to|with)\s+(.+)", t):
        return {"action": "disclose", "merchant_hint": f"marketplace:{m.group(2).strip(' .')}", "amount": None,
                "disclose": ["address"]}
    return {"action": "unknown", "merchant_hint": None, "amount": amount}


async def resolve_merchant(conn, user: str, hint: str | None, action: str) -> tuple[str | None, list[int]]:
    """Exact/substring match on the user's own merchants first; else pgvector recall over memories."""
    if not hint:
        return None, []
    if hint.startswith("marketplace:"):
        return hint, []
    row = await conn.fetchrow("""SELECT merchant FROM life_events WHERE user_id=$1 AND merchant IS NOT NULL
        AND (lower(merchant) LIKE '%'||$2||'%' OR $2 LIKE '%'||lower(merchant)||'%')
        GROUP BY merchant ORDER BY count(*) DESC LIMIT 1""", user, hint)
    if row:
        return row["merchant"], []
    kinds = ["bill"] if action == "pay_bill" else ["subscription"] if action == "cancel_subscription" else None
    hits = await conn.fetch("SELECT * FROM recall($1, $2::vector, $3, NULL, '400 days', 3)", user,
                            vec_literal(text_embedding(f"{hint} {action.replace('_', ' ')}")), kinds)
    if hits and hits[0]["similarity"] > 0.25:
        ev = await conn.fetchrow("SELECT merchant FROM life_events WHERE event_id=$1", hits[0]["source_event_id"])
        if ev and ev["merchant"]:
            return ev["merchant"], [h["source_event_id"] for h in hits[:1] if h["source_event_id"]]
    return hint.title(), []


async def scam_check(conn, text: str) -> dict:
    v = vec_literal(text_embedding(text))
    rows = await conn.fetch("""SELECT title, is_scam, (1-(embedding <=> $1::vector))::real AS sim
                               FROM scam_storylines ORDER BY embedding <=> $1::vector LIMIT 3""", v)
    top = rows[0] if rows else None
    hint = sum(1 for h in SCAM_HINTS if h in text.lower())
    base = (top["sim"] if top and top["is_scam"] else 0.0)
    score = min(1.0, base + 0.12 * hint)
    return {"score": round(score, 3), "nearest": top["title"] if top else None, "hint_terms": hint}


# ---------------------------------------------------------------- context
async def build_context(conn, user: str, text: str, source: str, at: datetime, scam: dict | None) -> tuple[dict, list[int]]:
    p = parse(text)
    merchant, evidence = await resolve_merchant(conn, user, p.get("merchant_hint"), p["action"])
    intent = {"action": p["action"], "merchant": merchant, "amount": p.get("amount"),
              "item": p.get("item"), "disclose": p.get("disclose", [])}
    assumptions = []
    if p["action"] == "pay_bill":
        bill = await conn.fetchrow("""SELECT event_id, amount, ts FROM life_events WHERE user_id=$1 AND merchant=$2
            AND kind='bill' AND NOT (detail ? 'by_agent') ORDER BY ts DESC LIMIT 1""", user, merchant)
        if bill:
            evidence.append(bill["event_id"])
            if intent["amount"] is None:
                intent["amount"] = float(bill["amount"])
        else:
            assumptions.append(f"no bill from {merchant} found in memory")
            if intent["amount"] is None:
                assumptions.append("amount unknown")
    elif p["action"] == "cancel_subscription":
        sub = await conn.fetchrow("""SELECT event_id FROM life_events WHERE user_id=$1 AND merchant=$2 AND kind='subscription'
            ORDER BY ts DESC LIMIT 1""", user, merchant)
        if sub:
            evidence.append(sub["event_id"])
        else:
            assumptions.append(f"no active {merchant} subscription found")
    elif p["action"] in ("purchase", "book") and intent["amount"] is None:
        assumptions.append("price not stated")
    if p["action"] == "disclose":
        addr = await conn.fetchrow("SELECT source_event_id FROM memories WHERE user_id=$1 AND data_class='address' LIMIT 1", user)
        if addr and addr["source_event_id"]:
            evidence.append(addr["source_event_id"])

    mandates = [dict(r) | {"max_amount": float(r["max_amount"]) if r["max_amount"] is not None else None,
                           "monthly_cap": float(r["monthly_cap"]) if r["monthly_cap"] is not None else None,
                           "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                           "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
                           "created_at": r["created_at"].isoformat()}
                for r in await conn.fetch("""SELECT mandate_id, kind, action, counterparty, max_amount, monthly_cap, disclose,
                    uses_left, daily_action_budget, expires_at, revoked_at, created_at FROM mandates
                    WHERE user_id=$1 AND created_at <= $2 AND (revoked_at IS NULL OR revoked_at > $2)""", user, at)]
    stats = await conn.fetch("""SELECT mandate_id,
            coalesce(sum(amount) FILTER (WHERE ts > $2::timestamptz - interval '30 days'),0) AS spend,
            count(*) AS uses,
            count(*) FILTER (WHERE ts > date_trunc('day', $2::timestamptz)) AS today
        FROM actions WHERE user_id=$1 AND decision='executed_simulated' AND mandate_id IS NOT NULL AND ts <= $2
        GROUP BY 1""", user, at)
    base = await conn.fetchrow("SELECT * FROM merchant_baseline($1,$2)", user, merchant or "") if merchant else None
    tool = await conn.fetchrow("SELECT tool_id, reputation, drift_flag, irreversible FROM tools WHERE tool_id=$1",
                               TOOL_FOR.get(p["action"], ""))
    ctx = {"at": at.isoformat(), "user_id": user, "source": source, "request": text, "intent": intent,
           "mandates": mandates,
           "mandate_spend_30d": {s["mandate_id"]: float(s["spend"]) for s in stats},
           "mandate_uses": {s["mandate_id"]: int(s["uses"]) for s in stats},
           "mandate_today": {s["mandate_id"]: int(s["today"]) for s in stats},
           "baseline": ({k: (float(v) if isinstance(v, (int, float)) or hasattr(v, "as_tuple") else
                             v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(base).items()}
                        if base else None),
           "tool": dict(tool) | {"reputation": float(tool["reputation"])} if tool else None,
           "scam": scam or {"score": 0.0, "nearest": None}, "assumptions": assumptions, "evidence": evidence}
    return ctx, evidence


# ---------------------------------------------------------------- receipts
async def append_receipt(conn, user: str, action_id: uuid.UUID, at: datetime, payload: dict) -> dict:
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", user)
    last = await conn.fetchrow("SELECT seq, hash FROM receipts WHERE user_id=$1 ORDER BY seq DESC LIMIT 1", user)
    seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, "0" * 64)
    pj = json.dumps(payload, sort_keys=True, default=str)
    h = await conn.fetchval("SELECT encode(sha256(convert_to($1 || $2::jsonb::text,'UTF8')),'hex')", prev, pj)
    await conn.execute("""INSERT INTO receipts (user_id, seq, ts, action_id, payload, prev_hash, hash, signature)
                          VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)""", user, seq, at, action_id, pj, prev, h, sign(h))
    return {"seq": seq, "hash": h, "prev_hash": prev}


async def handle(pool, user: str, text: str, source: str = "user", at: datetime | None = None,
                 scam: dict | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    text = (text or "").strip()
    if not 3 <= len(text) <= 500:
        raise AgentError("request must be 3..500 characters")
    async with pool.acquire() as conn:
        async with conn.transaction():
            ctx, evidence = await build_context(conn, user, text, source, at, scam)
            res = evaluate(ctx)
            aid = uuid.uuid4()
            it = ctx["intent"]
            ctx_hash = hashlib.sha256(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()
            await conn.execute("""INSERT INTO actions (ts, action_id, user_id, request, source, intent, context, evidence,
                assumptions, decision, reasons, mandate_id, tool_id, merchant, amount, policy_version)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9::jsonb,$10,$11::jsonb,$12,$13,$14,$15,$16)""",
                at, aid, user, text, source, json.dumps(it), json.dumps(ctx, default=str), evidence,
                json.dumps(ctx["assumptions"]), res["decision"], json.dumps(res["reasons"]), res["mandate_id"],
                (ctx["tool"] or {}).get("tool_id"), it.get("merchant"), it.get("amount"), POLICY_VERSION)
            execd = None
            if res["decision"] == "executed_simulated":
                execd = await _execute(conn, user, it, aid, text, at)
            payload = {"action_id": str(aid), "at": at.isoformat(), "user_id": user, "request": text, "source": source,
                       "intent": it, "decision": res["decision"], "reasons": res["reasons"], "evidence": evidence,
                       "assumptions": ctx["assumptions"], "mandate_id": res["mandate_id"],
                       "tool_id": (ctx["tool"] or {}).get("tool_id"), "policy_version": POLICY_VERSION,
                       "context_sha256": ctx_hash, "simulated": True,
                       "execution": execd}
            rc = await append_receipt(conn, user, aid, at, payload)
    return {"action_id": str(aid), **res, "intent": it, "evidence": evidence, "assumptions": ctx["assumptions"],
            "receipt": rc}


async def _execute(conn, user, it, aid, text, at) -> dict | None:
    """Call the adapter (idempotent on action_id) and mirror money-moving results into life memory."""
    r = await adp.execute(ADAPTERS, user, it, str(aid), text)
    if r is None:
        return None
    if it["action"] in ("pay_bill", "purchase", "book") and it.get("amount"):
        await conn.execute("""INSERT INTO life_events (ts,user_id,kind,merchant,category,amount,detail)
            VALUES ($1,$2,'txn',$3,'agent',$4,$5::jsonb)""", at, user, it["merchant"], it["amount"],
            json.dumps({"by_agent": True, "simulated": r.simulated, "action_id": str(aid), "provider_ref": r.provider_ref}))
    return {"ok": r.ok, "provider_ref": r.provider_ref, "simulated": r.simulated}


async def decide(pool, user: str, action_id: str, approve: bool) -> dict:
    """Owner approves/denies a needs_approval action exactly once. Approval executes via the adapter; both receipted."""
    at = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            a = await conn.fetchrow("SELECT * FROM actions WHERE action_id=$1 AND user_id=$2", uuid.UUID(action_id), user)
            if not a:
                raise AgentError("no such action")
            if a["decision"] != "needs_approval":
                raise AgentError(f"action is {a['decision']}, not awaiting approval")
            ins = await conn.fetchval("""INSERT INTO approvals (action_id,user_id,outcome) VALUES ($1,$2,$3)
                ON CONFLICT DO NOTHING RETURNING action_id""", a["action_id"], user, "approved" if approve else "denied")
            if not ins:
                raise AgentError("already decided")
            it = json.loads(a["intent"])
            execd = await _execute(conn, user, it, a["action_id"], a["request"], at) if approve else None
            payload = {"action_id": str(a["action_id"]), "at": at.isoformat(), "user_id": user,
                       "event": "user_approved" if approve else "user_denied", "intent": it,
                       "execution": execd, "policy_version": POLICY_VERSION, "simulated": True}
            rc = await append_receipt(conn, user, a["action_id"], at, payload)
    return {"action_id": action_id, "outcome": "approved" if approve else "denied", "execution": execd, "receipt": rc}


async def handle_inbound(pool, user: str, channel: str, sender: str, body: str, at: datetime | None = None) -> dict:
    """A third party asks the user (and so the agent) to do something. Scam-check first, then plan like any request."""
    at = at or datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        sc = await scam_check(conn, body)
        iid = await conn.fetchval("""INSERT INTO inbound (ts,user_id,channel,sender,body,scam_score,nearest)
            VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING inbound_id""", at, user, channel, sender, body, sc["score"], sc["nearest"])
    return await handle(pool, user, body, source=f"inbound:{iid}:{sender}", at=at, scam=sc)


# ---------------------------------------------------------------- verification + replay
async def verify(pool, user: str) -> dict:
    async with pool.acquire() as conn:
        chain = await conn.fetch("SELECT * FROM verify_chain($1)", user)
        sigs = await conn.fetch("SELECT seq, hash, signature FROM receipts WHERE user_id=$1 ORDER BY seq", user)
    bad = [c["seq"] for c in chain if not (c["ok_link"] and c["ok_hash"])]
    badsig = [s["seq"] for s in sigs if not hmac.compare_digest(sign(s["hash"]), s["signature"])]
    return {"receipts": len(chain), "broken_links_or_hashes": bad, "bad_signatures": badsig,
            "ok": not bad and not badsig}


async def replay(pool, user: str, since_days: int = 30, params: dict | None = None,
                 mandate_patch: list[dict] | None = None) -> dict:
    """Re-run the frozen context of every past action under (a) the original policy -> must reproduce, and
    (b) a proposed policy/mandate change -> diff. This is the 'what if I had set this rule?' simulator."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT action_id, ts, request, decision, context FROM actions
            WHERE user_id=$1 AND ts > now() - make_interval(days => $2) ORDER BY ts""", user, since_days)
    reproduced, diffs = 0, []
    for r in rows:
        ctx = json.loads(r["context"])
        if evaluate(ctx)["decision"] == r["decision"]:
            reproduced += 1
        mands = ctx["mandates"]
        if mandate_patch:
            byid = {m["mandate_id"]: m for m in mands}
            for pm in mandate_patch:
                if pm.get("delete"):
                    byid.pop(pm["mandate_id"], None)
                else:
                    byid[pm["mandate_id"]] = {**byid.get(pm["mandate_id"], {"disclose": [], "counterparty": "*", "kind": "standing", "action": "__none__"}), **pm}
            mands = list(byid.values())
        new = evaluate(ctx, params=params, mandates=mands)
        if new["decision"] != r["decision"]:
            changed = [x for x in new["reasons"] if x["outcome"] != "pass"]
            diffs.append({"action_id": str(r["action_id"]), "ts": r["ts"].isoformat(), "request": r["request"],
                          "was": r["decision"], "would_be": new["decision"], "because": changed})
    return {"actions": len(rows), "reproduced_exactly": reproduced, "changed": len(diffs), "diffs": diffs}
