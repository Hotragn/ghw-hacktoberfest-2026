"""Tool registry: built-in tools (memory, web fetch, calendar via ICS/CalDAV, email via IMAP/SMTP, sandboxed files,
payments) plus any tool exposed by a user-connected MCP server. Each tool declares its scope (read/write/spend),
data class and whether its output is untrusted; the runtime's gate uses those declarations, never the model."""
from __future__ import annotations
import asyncio
import email
import email.utils
import imaplib
import ipaddress
import json
import os
import re
import smtplib
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
import httpx

from witness import mcp, memory, payments


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    scope: str                 # read | write | spend
    data_class: str = "personal"
    untrusted_output: bool = False
    internal: bool = False     # memory tools: user-visible/forgettable, no grant needed (taint rule still applies)
    egress: bool = False       # sends data outside (email, http POST, mcp write)
    fn: Callable[..., Awaitable[str]] | None = None
    mcp_server: str | None = None

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@dataclass
class Services:
    """Side-effecting dependencies, injectable for tests."""
    http_transport: Any = None
    resolve: Callable[[str], list[str]] | None = None
    rail: payments.PaymentRail = field(default_factory=payments.rail_from_env)
    smtp_send: Callable[[dict, EmailMessage], None] | None = None
    imap_fetch: Callable[[dict, str, int], list[dict]] | None = None
    files_root: str = field(default_factory=lambda: os.environ.get("WITNESS_FILES_ROOT", "/tmp/witness-files"))
    mcp_http_transport: Any = None


@dataclass
class Ctx:
    conn: Any
    user: str
    task_id: uuid.UUID
    services: Services
    call_id: str = ""


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


# ------------------------------------------------------------------ network guard
class FetchError(ValueError):
    pass


def _default_resolve(host: str) -> list[str]:
    return [ai[4][0] for ai in socket.getaddrinfo(host, None)]


def check_url(url: str, services: Services) -> str:
    u = urlparse(url)
    if u.scheme not in ("https", "http") or not u.hostname:
        raise FetchError("only http(s) URLs are allowed")
    if os.environ.get("WITNESS_ALLOW_PRIVATE_FETCH", "false").lower() == "true":
        return url
    for ip in (services.resolve or _default_resolve)(u.hostname):
        a = ipaddress.ip_address(ip)
        if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
            raise FetchError(f"refusing to fetch private address {ip} (SSRF guard)")
    return url


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip and d.strip():
            self.out.append(d.strip())


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\s+\n", "\n", "\n".join(p.out))


async def _get(ctx: Ctx, url: str, max_bytes: int = 300_000, **kw) -> httpx.Response:
    check_url(url, ctx.services)
    async with httpx.AsyncClient(timeout=20, transport=ctx.services.http_transport, follow_redirects=False) as c:
        for _ in range(4):  # follow redirects manually so every hop passes the SSRF guard
            r = await c.get(url, **kw)
            if r.is_redirect and r.headers.get("location"):
                url = check_url(str(r.url.join(r.headers["location"])), ctx.services)
                continue
            if len(r.content) > max_bytes:
                r._content = r.content[:max_bytes]
            return r
    raise FetchError("too many redirects")


# ------------------------------------------------------------------ built-ins
async def t_web_fetch(ctx: Ctx, url: str) -> str:
    r = await _get(ctx, url)
    ct = r.headers.get("content-type", "")
    text = html_to_text(r.text) if "html" in ct else r.text
    return f"HTTP {r.status_code} {url}\n{text[:12000]}"


async def t_memory_save(ctx: Ctx, text: str, kind: str = "fact") -> str:
    m = await memory.add(ctx.conn, ctx.user, text, kind=kind, source="agent", confidence=0.9)
    return json.dumps({"saved": m["memory_id"], "text": m["text"]})


async def t_memory_search(ctx: Ctx, query: str) -> str:
    items = await memory.search(ctx.conn, ctx.user, query, 5)
    return json.dumps([{"id": i["memory_id"], "kind": i["kind"], "text": i["text"], "score": round(i["score"], 3)} for i in items])


def parse_ics(text: str) -> list[dict]:
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold
    events, cur = [], None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            k, v = line.split(":", 1)
            key = k.split(";")[0].upper()
            if key in ("DTSTART", "DTEND"):
                cur[key.lower()] = _ics_dt(v)
            elif key in ("SUMMARY", "LOCATION", "DESCRIPTION", "UID"):
                cur[key.lower()] = v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
    return events


def _ics_dt(v: str) -> str:
    v = v.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            d = datetime.strptime(v, fmt)
            if fmt.endswith("Z"):
                d = d.replace(tzinfo=timezone.utc)
            return d.isoformat()
        except ValueError:
            pass
    return v


async def _connector(ctx: Ctx, kind: str) -> dict:
    r = await ctx.conn.fetchval("SELECT config FROM connectors WHERE user_id=$1 AND kind=$2", ctx.user, kind)
    if not r:
        raise FetchError(f"no {kind} connector configured (Settings > Connectors)")
    return json.loads(r)


def _secret(cfg: dict) -> str | None:
    return os.environ.get(cfg["secret_env"]) if cfg.get("secret_env") else None


async def t_calendar_list(ctx: Ctx, days: int = 7) -> str:
    try:
        cfg, kind = await _connector(ctx, "ics"), "ics"
    except FetchError:
        cfg, kind = await _connector(ctx, "caldav"), "caldav"
    auth = (cfg.get("username"), _secret(cfg)) if cfg.get("username") else None
    r = await _get(ctx, cfg["url"], auth=auth)
    evs = parse_ics(r.text)
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=int(days))
    out = []
    for e in evs:
        try:
            s = datetime.fromisoformat(e.get("dtstart", ""))
            s = s if s.tzinfo else s.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - timedelta(hours=12) <= s <= horizon:
            out.append(e)
    out.sort(key=lambda e: e["dtstart"])
    return json.dumps({"source": kind, "events": out[:50]})


async def t_calendar_add(ctx: Ctx, title: str, start: str, end: str, location: str = "") -> str:
    cfg = await _connector(ctx, "caldav")
    uid = uuid.uuid4().hex
    fmt = lambda s: datetime.fromisoformat(s).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Witness//EN\r\nBEGIN:VEVENT\r\n"
           f"UID:{uid}\r\nDTSTAMP:{fmt(datetime.now(timezone.utc).isoformat())}\r\nDTSTART:{fmt(start)}\r\nDTEND:{fmt(end)}\r\n"
           f"SUMMARY:{title}\r\nLOCATION:{location}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    url = cfg["url"].rstrip("/") + f"/{uid}.ics"
    check_url(url, ctx.services)
    async with httpx.AsyncClient(timeout=20, transport=ctx.services.http_transport) as c:
        r = await c.put(url, content=ics, headers={"Content-Type": "text/calendar", "If-None-Match": "*"},
                        auth=(cfg.get("username"), _secret(cfg)) if cfg.get("username") else None)
    if r.status_code not in (200, 201, 204):
        raise FetchError(f"CalDAV PUT failed: HTTP {r.status_code}")
    return json.dumps({"created": uid, "title": title, "start": start})


def _imap_fetch_default(cfg: dict, query: str, limit: int) -> list[dict]:
    m = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port", 993)), timeout=20)
    try:
        m.login(cfg["username"], _secret(cfg) or "")
        m.select(cfg.get("mailbox", "INBOX"), readonly=True)
        crit = ["TEXT", json.dumps(query)] if query else ["ALL"]
        _, data = m.search("UTF-8" if query else None, *crit)
        ids = data[0].split()[-limit:]
        out = []
        for i in reversed(ids):
            _, d = m.fetch(i, "(BODY.PEEK[])")
            msg = email.message_from_bytes(d[0][1])
            body = ""
            part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
            if part is None and not msg.is_multipart():
                body = msg.get_payload(decode=True).decode(errors="replace")
            elif part is not None:
                body = part.get_content() if hasattr(part, "get_content") else str(part.get_payload())
            out.append({"from": msg.get("From"), "subject": msg.get("Subject"), "date": msg.get("Date"), "body": body[:2000]})
        return out
    finally:
        m.logout()


async def t_email_search(ctx: Ctx, query: str = "", limit: int = 5) -> str:
    cfg = await _connector(ctx, "imap")
    fn = ctx.services.imap_fetch or _imap_fetch_default
    msgs = await asyncio.to_thread(fn, cfg, query, max(1, min(int(limit), 20)))
    return json.dumps(msgs)


def _smtp_send_default(cfg: dict, msg: EmailMessage) -> None:
    with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)), timeout=20) as s:
        s.starttls()
        s.login(cfg["username"], _secret(cfg) or "")
        s.send_message(msg)


async def t_email_send(ctx: Ctx, to: str, subject: str, body: str) -> str:
    if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", to):
        raise FetchError("invalid recipient")
    cfg = await _connector(ctx, "smtp")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.get("from", cfg["username"]), to, subject[:200]
    msg["Message-ID"] = email.utils.make_msgid(domain="witness.local")
    msg["X-Witness-Task"] = str(ctx.task_id)
    msg.set_content(body[:20000] + "\n\n-- sent by my Witness agent (AI) on my behalf")  # EU AI Act art. 50 disclosure
    await asyncio.to_thread(ctx.services.smtp_send or _smtp_send_default, cfg, msg)
    return json.dumps({"sent": True, "to": to, "message_id": msg["Message-ID"]})


def _safe_path(ctx: Ctx, path: str) -> str:
    root = os.path.realpath(os.path.join(ctx.services.files_root, re.sub(r"[^\w.-]", "_", ctx.user)))
    os.makedirs(root, exist_ok=True)
    p = os.path.realpath(os.path.join(root, path))
    if not (p == root or p.startswith(root + os.sep)):
        raise FetchError("path escapes the sandbox")
    return p


async def t_files_list(ctx: Ctx) -> str:
    root = _safe_path(ctx, ".")
    return json.dumps(sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)[:500])


async def t_files_read(ctx: Ctx, path: str) -> str:
    with open(_safe_path(ctx, path), encoding="utf-8", errors="replace") as f:
        return f.read(50_000)


async def t_files_write(ctx: Ctx, path: str, content: str) -> str:
    p = _safe_path(ctx, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content[:200_000])
    return json.dumps({"written": path, "bytes": len(content.encode())})


async def t_pay(ctx: Ctx, merchant: str, amount: float, currency: str = "USD", description: str = "",
                items: list | None = None) -> str:
    amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    mandate, reasons = await payments.check(ctx.conn, ctx.user, merchant, amt, currency)
    if not mandate:
        raise payments.PaymentError("; ".join(r.get("fail", "") for r in reasons))
    p = await payments.execute(ctx.conn, ctx.services.rail, ctx.user, mandate, merchant, amt, currency,
                               items or ([{"description": description}] if description else []),
                               f"{ctx.task_id}:{ctx.call_id}")
    return json.dumps({"payment_id": p["payment_id"], "status": p["status"], "mandate_id": p["mandate_id"],
                       "checkout_hash": p["checkout_hash"], "rail": p["rail"], "provider_ref": p["provider_ref"]})


BUILTINS: list[Tool] = [
    Tool("memory_save", "Save a durable fact or preference about the user (user can see/edit/forget it).",
         _obj({"text": {"type": "string"}, "kind": {"type": "string", "enum": list(memory.KINDS)}}, ["text"]),
         "write", internal=True, fn=t_memory_save),
    Tool("memory_search", "Search what you know about the user.", _obj({"query": {"type": "string"}}, ["query"]),
         "read", internal=True, fn=t_memory_search),
    Tool("web_fetch", "Fetch a public web page and return its text.", _obj({"url": {"type": "string"}}, ["url"]),
         "read", data_class="public", untrusted_output=True, fn=t_web_fetch),
    Tool("calendar_list", "List upcoming calendar events (ICS feed or CalDAV).",
         _obj({"days": {"type": "integer", "minimum": 1, "maximum": 60}}), "read", untrusted_output=True, fn=t_calendar_list),
    Tool("calendar_add", "Create a calendar event via CalDAV.",
         _obj({"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
               "location": {"type": "string"}}, ["title", "start", "end"]), "write", fn=t_calendar_add),
    Tool("email_search", "Search the user's mailbox (IMAP).",
         _obj({"query": {"type": "string"}, "limit": {"type": "integer"}}), "read", untrusted_output=True, fn=t_email_search),
    Tool("email_send", "Send an email from the user's account (SMTP).",
         _obj({"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, ["to", "subject", "body"]),
         "write", egress=True, fn=t_email_send),
    Tool("files_list", "List files in the user's sandbox.", _obj({}), "read", fn=t_files_list),
    Tool("files_read", "Read a file from the user's sandbox.", _obj({"path": {"type": "string"}}, ["path"]),
         "read", untrusted_output=True, fn=t_files_read),
    Tool("files_write", "Write a file in the user's sandbox.",
         _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]), "write", fn=t_files_write),
    Tool("pay", "Pay a merchant under one of the user's payment mandates (AP2-style).",
         _obj({"merchant": {"type": "string"}, "amount": {"type": "number"}, "currency": {"type": "string"},
               "description": {"type": "string"}, "items": {"type": "array", "items": {"type": "object"}}},
              ["merchant", "amount"]), "spend", data_class="financial", egress=True, fn=t_pay),
]


class Registry:
    def __init__(self, tools: list[Tool] | None = None):
        self.tools = {t.name: t for t in (tools or BUILTINS)}
        self._mcp_clients: list = []

    def specs(self) -> list[dict]:
        return [t.spec() for t in self.tools.values()]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    async def load_mcp(self, conn, user: str, services: Services) -> list[str]:
        """Connect every MCP server the user registered and expose its tools as mcp:<server>/<tool>."""
        errors = []
        for s in await conn.fetch("SELECT * FROM mcp_servers WHERE user_id=$1", user):
            try:
                c = await mcp.connect(s["transport"], s["target"], s["auth_env"], services.mcp_http_transport)
                self._mcp_clients.append(c)
                for t in await c.list_tools():
                    ann = t.get("annotations") or {}
                    name = f"mcp:{s['name']}/{t['name']}"

                    async def run(ctx, _c=c, _n=t["name"], **args):
                        res = await _c.call_tool(_n, args)
                        txt = mcp.result_text(res)
                        if res.get("isError"):
                            raise FetchError(txt[:500])
                        return txt
                    self.tools[name] = Tool(name, (t.get("description") or "")[:500],
                                            t.get("inputSchema") or _obj({}), "read" if ann.get("readOnlyHint") else "write",
                                            untrusted_output=True, egress=not ann.get("readOnlyHint"), fn=run,
                                            mcp_server=s["name"])
            except Exception as e:  # one bad server must not break the agent
                errors.append(f"{s['name']}: {e}")
        return errors

    async def close(self):
        for c in self._mcp_clients:
            await c.close()
