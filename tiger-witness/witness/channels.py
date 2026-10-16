"""Messaging channels: users talk to Witness where they already chat.
- Telegram Bot API (webhook secret header; inline Approve/Deny buttons)
- WhatsApp Business Cloud API (hub.verify_token handshake; X-Hub-Signature-256 HMAC; interactive reply buttons)
- iMessage via a self-hosted Mac relay (BlueBubbles server REST API + webhook). Apple has no public iMessage API,
  so this REQUIRES a Mac you control running BlueBubbles, signed in to the iMessage account.
- Generic signed webhook (HMAC-SHA256 over timestamp.body, 5-minute replay window) for anything else.
Every adapter normalises to Inbound(channel, external_id, text) and routes through the same agent + gate."""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import httpx

from witness.agent import signing_key
from witness.db import system_tx, user_tx

CHANNELS = ("telegram", "whatsapp", "imessage", "webhook")


@dataclass
class Inbound:
    channel: str
    external_id: str
    text: str
    approval_action: tuple[str, bool] | None = None  # (approval_id, approve) from a button tap
    message_id: str | None = None                    # provider message id: queue dedupe key (webhook retries are no-ops)

    def job(self) -> tuple[dict, str | None]:
        return ({"channel": self.channel, "external_id": self.external_id, "text": self.text,
                 "approval_action": list(self.approval_action) if self.approval_action else None, "message_id": self.message_id},
                f"{self.channel}:{self.message_id}" if self.message_id else None)


# ------------------------------------------------------------------ senders
class TelegramSender:
    def __init__(self, token: str, transport=None):
        self.token, self.transport = token, transport

    async def send(self, external_id: str, text: str, approval_id: str | None = None):
        body = {"chat_id": external_id, "text": text[:4000]}
        if approval_id:
            body["reply_markup"] = {"inline_keyboard": [[{"text": "Approve", "callback_data": f"a:{approval_id}"},
                                                         {"text": "Deny", "callback_data": f"d:{approval_id}"}]]}
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as c:
            r = await c.post(f"https://api.telegram.org/bot{self.token}/sendMessage", json=body)
            r.raise_for_status()


class WhatsAppSender:
    API = "https://graph.facebook.com/v21.0"

    def __init__(self, token: str, phone_number_id: str, transport=None):
        self.token, self.phone_id, self.transport = token, phone_number_id, transport

    async def send(self, external_id: str, text: str, approval_id: str | None = None):
        if approval_id:
            body = {"messaging_product": "whatsapp", "to": external_id, "type": "interactive", "interactive": {
                "type": "button", "body": {"text": text[:1024]}, "action": {"buttons": [
                    {"type": "reply", "reply": {"id": f"a:{approval_id}", "title": "Approve"}},
                    {"type": "reply", "reply": {"id": f"d:{approval_id}", "title": "Deny"}}]}}}
        else:
            body = {"messaging_product": "whatsapp", "to": external_id, "type": "text", "text": {"body": text[:4096]}}
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as c:
            r = await c.post(f"{self.API}/{self.phone_id}/messages", json=body,
                             headers={"Authorization": f"Bearer {self.token}"})
            r.raise_for_status()


class BlueBubblesSender:
    """iMessage through a BlueBubbles server on the user's Mac (REST: POST /api/v1/message/text?password=...)."""

    def __init__(self, base_url: str, password: str, transport=None):
        self.base, self.password, self.transport = base_url.rstrip("/"), password, transport

    async def send(self, external_id: str, text: str, approval_id: str | None = None):
        if approval_id:
            text += f"\n\nReply APPROVE {approval_id[:8]} or DENY {approval_id[:8]}"
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as c:
            r = await c.post(f"{self.base}/api/v1/message/text", params={"password": self.password},
                             json={"chatGuid": external_id, "message": text[:8000], "tempGuid": f"witness-{uuid.uuid4()}",
                                   "method": os.environ.get("IMESSAGE_SEND_METHOD", "apple-script")})
            r.raise_for_status()


def senders_from_env(transport=None) -> dict:
    s = {}
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        s["telegram"] = TelegramSender(os.environ["TELEGRAM_BOT_TOKEN"], transport)
    if os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"):
        s["whatsapp"] = WhatsAppSender(os.environ["WHATSAPP_TOKEN"], os.environ["WHATSAPP_PHONE_NUMBER_ID"], transport)
    if os.environ.get("IMESSAGE_BLUEBUBBLES_URL") and os.environ.get("IMESSAGE_BLUEBUBBLES_PASSWORD"):
        s["imessage"] = BlueBubblesSender(os.environ["IMESSAGE_BLUEBUBBLES_URL"], os.environ["IMESSAGE_BLUEBUBBLES_PASSWORD"], transport)
    return s


# ------------------------------------------------------------------ inbound verification + parsing
def ct_eq(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def telegram_verify(header_secret: str | None) -> bool:
    return ct_eq(header_secret, os.environ.get("TELEGRAM_WEBHOOK_SECRET"))


def telegram_parse(update: dict) -> Inbound | None:
    if cq := update.get("callback_query"):
        m = re.fullmatch(r"([ad]):([0-9a-f-]{36})", cq.get("data", ""))
        chat = (cq.get("message") or {}).get("chat", {}).get("id") or cq.get("from", {}).get("id")
        if m and chat:
            return Inbound("telegram", str(chat), "", (m.group(2), m.group(1) == "a"), f"cb{cq.get('id', '')}" if cq.get("id") else None)
        return None
    msg = update.get("message") or update.get("edited_message")
    if msg and msg.get("text") and msg.get("chat"):
        return Inbound("telegram", str(msg["chat"]["id"]), msg["text"],
                       message_id=str(update["update_id"]) if "update_id" in update else None)
    return None


def whatsapp_verify_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    if mode == "subscribe" and ct_eq(token, os.environ.get("WHATSAPP_VERIFY_TOKEN")):
        return challenge
    return None


def whatsapp_verify_signature(raw: bytes, header: str | None) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret or not header or not header.startswith("sha256="):
        return False
    return ct_eq(header[7:], hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest())


def whatsapp_parse(payload: dict) -> list[Inbound]:
    out = []
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            for m in (ch.get("value") or {}).get("messages", []) or []:
                if m.get("type") == "text":
                    out.append(Inbound("whatsapp", m["from"], m["text"]["body"], message_id=m.get("id")))
                elif m.get("type") == "interactive":
                    rid = (m["interactive"].get("button_reply") or {}).get("id", "")
                    mm = re.fullmatch(r"([ad]):([0-9a-f-]{36})", rid)
                    if mm:
                        out.append(Inbound("whatsapp", m["from"], "", (mm.group(2), mm.group(1) == "a"), m.get("id")))
    return out


def imessage_verify(token: str | None) -> bool:
    return ct_eq(token, os.environ.get("IMESSAGE_WEBHOOK_SECRET"))


def imessage_parse(payload: dict) -> Inbound | None:
    if payload.get("type") != "new-message":
        return None
    d = payload.get("data") or {}
    if d.get("isFromMe") or not d.get("text"):
        return None  # never react to our own outgoing messages (loop guard)
    chats = d.get("chats") or []
    guid = chats[0]["guid"] if chats else f"iMessage;-;{(d.get('handle') or {}).get('address', '')}"
    return Inbound("imessage", guid, d["text"], message_id=d.get("guid"))


def webhook_secret(user_id: str) -> str:
    """Per-user webhook secret derived from the server key: nothing extra to store or leak from the DB."""
    return hmac.new(signing_key(), b"webhook|" + user_id.encode(), hashlib.sha256).hexdigest()


def webhook_verify(user_id: str, ts: str | None, sig: str | None, raw: bytes, now: float | None = None) -> bool:
    try:
        if abs((now or time.time()) - int(ts)) > 300:
            return False
    except (TypeError, ValueError):
        return False
    exp = hmac.new(webhook_secret(user_id).encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return ct_eq((sig or "").removeprefix("sha256="), exp)


# ------------------------------------------------------------------ linking + routing
async def new_link_code(pool, user: str, channel: str) -> str:
    code = secrets.token_hex(4).upper()
    async with user_tx(pool, user) as conn:
        await conn.execute("INSERT INTO link_codes (code_sha256,user_id,channel,expires_at) VALUES ($1,$2,$3,$4)",
                           hashlib.sha256(code.encode()).hexdigest(), user, channel,
                           datetime.now(timezone.utc) + timedelta(minutes=15))
    return code


async def resolve(pool, inb: Inbound) -> str | None:
    async with system_tx(pool) as conn:
        return await conn.fetchval("SELECT user_id FROM channel_links WHERE channel=$1 AND external_id=$2",
                                   inb.channel, inb.external_id)


async def try_link(pool, inb: Inbound) -> str | None:
    m = re.fullmatch(r"\s*(?:/start|link)\s+([0-9A-Fa-f]{8})\s*", inb.text or "")
    if not m:
        return None
    h = hashlib.sha256(m.group(1).upper().encode()).hexdigest()
    async with system_tx(pool) as conn:
        uid = await conn.fetchval("""UPDATE link_codes SET used_at=now() WHERE code_sha256=$1 AND channel=$2
            AND used_at IS NULL AND expires_at > now() RETURNING user_id""", h, inb.channel)
        if uid:
            await conn.execute("""INSERT INTO channel_links (channel,external_id,user_id) VALUES ($1,$2,$3)
                ON CONFLICT (channel,external_id) DO UPDATE SET user_id=EXCLUDED.user_id, linked_at=now()""",
                               inb.channel, inb.external_id, uid)
    return uid


async def text_decision(pool, user: str, text: str) -> tuple[str, bool] | None:
    """'APPROVE 1a2b3c4d' / 'DENY 1a2b3c4d' typed in chat (iMessage/SMS-style channels without buttons)."""
    m = re.fullmatch(r"\s*(approve|deny|yes|no)\s+([0-9a-f]{8})\s*", (text or "").lower())
    if not m:
        return None
    async with user_tx(pool, user) as conn:
        aid = await conn.fetchval("""SELECT approval_id::text FROM pending_approvals WHERE user_id=$1 AND status='pending'
            AND approval_id::text LIKE $2 || '%' ORDER BY created_at DESC LIMIT 1""", user, m.group(2))
    return (aid, m.group(1) in ("approve", "yes")) if aid else None


async def handle(pool, agent, inb: Inbound, sender=None, deferred: bool = False) -> dict:
    """Route one inbound chat message through linking, approvals and the agent; reply via the channel's sender.
    If every model provider is out of quota the turn is parked in the durable queue and the user gets
    "Saved, I'll reply by ~HH:MM"; when re-run from that queue (deferred=True) exhaustion re-parks the job."""
    from witness.router import QuotaExhausted
    async def reply(text, approval_id=None):
        if sender:
            await sender.send(inb.external_id, text, approval_id)
        return {"reply": text, "approval_id": approval_id}

    user = await resolve(pool, inb)
    if not user:
        uid = await try_link(pool, inb)
        if uid:
            return {**await reply("Linked. You can now chat with your Witness agent here."), "user_id": uid}
        return await reply("This chat isn't linked yet. In the Witness web app open Channels, create a code, then send: link <CODE>")
    decision = inb.approval_action or await text_decision(pool, user, inb.text)
    if decision:
        from witness.passkeys import PasskeyRequired
        try:
            res = await agent.decide(user, decision[0], decision[1])
        except PasskeyRequired:
            url = os.environ.get("WITNESS_PUBLIC_URL", "").rstrip("/") + "/app#approvals"
            return {**await reply(f"This one needs your passkey. Confirm it here: {url}"), "user_id": user, "status": "passkey_required"}
        except ValueError as e:
            return {**await reply(str(e)), "user_id": user, "status": "error"}
    else:
        try:
            res = await agent.run(user, inb.text, channel=inb.channel)
        except QuotaExhausted as q:
            if deferred:
                from witness.jobs import Defer
                raise Defer(q.retry_at) from None
            from witness import deferral
            when, _ = await deferral.defer_turn(pool, user, {"channel": inb.channel, "external_id": inb.external_id,
                                                             "text": inb.text, "message_id": inb.message_id}, q.retry_at)
            return {**await reply(deferral.saved_message(when)), "user_id": user, "status": "deferred", "retry_at": when}
    out = await reply(res["reply"], res.get("approval_id"))
    return {**out, "user_id": user, "task_id": res["task_id"], "status": res["status"]}
