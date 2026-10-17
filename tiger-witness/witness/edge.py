"""Edge-to-origin trust, security headers, CORS and per-sender rate limiting for the public deployment.

Worker -> Space HMAC (WITNESS_EDGE_SECRET, shared only between the Cloudflare secret store and the HF secret store):
    X-Witness-Edge-Ts:    unix seconds
    X-Witness-Edge-Nonce: 16+ random hex chars, single use
    X-Witness-Edge-Sig:   hex HMAC-SHA256(secret, f"{ts}.{nonce}.{METHOD}.{path?query}.{sha256(body)}")
Rejected when the timestamp is outside +/-WITNESS_EDGE_SKEW_S (default 60s) or the nonce was already seen inside
that window (in-memory: the Space is a single replica; provider-level dedupe_key covers the rest).
This is on top of, never instead of, the provider signatures (Telegram secret token, WhatsApp X-Hub-Signature-256,
BlueBubbles shared secret), which the app keeps verifying.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from collections import OrderedDict

from fastapi import HTTPException, Request

from tigerprod import RateLimiter


def edge_secret() -> str | None:
    return os.environ.get("WITNESS_EDGE_SECRET") or None


def edge_required() -> bool:
    # default: required whenever a secret is configured; WITNESS_REQUIRE_EDGE=true without a secret fails closed
    v = os.environ.get("WITNESS_REQUIRE_EDGE", "auto").lower()
    return v == "true" or (v == "auto" and edge_secret() is not None)


def canonical(ts: str, nonce: str, method: str, path_qs: str, body: bytes) -> bytes:
    return f"{ts}.{nonce}.{method.upper()}.{path_qs}.{hashlib.sha256(body).hexdigest()}".encode()


def sign(secret: str, ts: str, nonce: str, method: str, path_qs: str, body: bytes) -> str:
    return hmac.new(secret.encode(), canonical(ts, nonce, method, path_qs, body), hashlib.sha256).hexdigest()


class NonceCache:
    def __init__(self, ttl: float, max_items: int = 100_000):
        self.ttl, self.max, self.seen = ttl, max_items, OrderedDict()

    def add(self, nonce: str, now: float) -> bool:
        """True if fresh (and records it); False on replay."""
        while self.seen and next(iter(self.seen.values())) < now - self.ttl:
            self.seen.popitem(last=False)
        if nonce in self.seen:
            return False
        self.seen[nonce] = now
        if len(self.seen) > self.max:
            self.seen.popitem(last=False)
        return True


_NONCE_RE = re.compile(r"[0-9a-f]{16,64}")
NONCES = NonceCache(ttl=2 * float(os.environ.get("WITNESS_EDGE_SKEW_S", "60")))


def verify(secret: str | None, ts: str | None, nonce: str | None, sig: str | None, method: str, path_qs: str,
           body: bytes, now: float | None = None, nonces: NonceCache | None = None) -> str | None:
    """None when valid, else a short reason."""
    if not secret:
        return "edge secret not configured"
    if not (ts and nonce and sig):
        return "missing edge signature"
    now = time.time() if now is None else now
    try:
        if abs(now - int(ts)) > float(os.environ.get("WITNESS_EDGE_SKEW_S", "60")):
            return "stale edge timestamp"
    except ValueError:
        return "bad edge timestamp"
    if not _NONCE_RE.fullmatch(nonce):
        return "bad edge nonce"
    if not hmac.compare_digest(sig.encode(), sign(secret, ts, nonce, method, path_qs, body).encode()):
        return "bad edge signature"
    if not (nonces or NONCES).add(nonce, now):
        return "replayed edge request"
    return None


async def edge_guard(req: Request) -> None:
    """FastAPI dependency for public webhook routes. Starlette caches req.body(), so routes can read it again."""
    if not edge_required():
        return
    body = await req.body()
    path_qs = req.url.path + (("?" + req.url.query) if req.url.query else "")
    h = req.headers
    why = verify(edge_secret(), h.get("x-witness-edge-ts"), h.get("x-witness-edge-nonce"),
                 h.get("x-witness-edge-sig"), req.method, path_qs, body)
    if why:
        raise HTTPException(401, why)


# ---------------------------------------------------------------- per-sender limits (chat id / phone, not IP)
SENDER_LIMITER = RateLimiter(float(os.environ.get("WITNESS_SENDER_RATE_PER_MIN", "20")),
                             int(os.environ.get("WITNESS_SENDER_BURST", "10")))


def sender_allowed(channel: str, sender: str, limiter: RateLimiter | None = None) -> bool:
    return (limiter or SENDER_LIMITER).allow(f"{channel}:{sender}")


# ---------------------------------------------------------------- security headers + CORS
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def security_headers(https: bool) -> dict[str, str]:
    h = {"content-security-policy": CSP, "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
         "cross-origin-opener-policy": "same-origin", "cross-origin-resource-policy": "same-origin",
         "x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer"}
    if https:
        h["strict-transport-security"] = "max-age=31536000; includeSubDomains"
    return h


def cors_origins() -> list[str]:
    """Explicit allow-list only (WITNESS_CORS_ORIGINS, comma separated). Empty = same-origin only (the default:
    the web app is served by the API itself, so no cross-origin access is needed)."""
    return [o.strip() for o in os.environ.get("WITNESS_CORS_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]


def install(app) -> None:
    from fastapi.middleware.cors import CORSMiddleware
    https = os.environ.get("WITNESS_COOKIE_SECURE", "false").lower() == "true"
    hdrs = security_headers(https)

    @app.middleware("http")
    async def _sec(request, call_next):
        resp = await call_next(request)
        for k, v in hdrs.items():
            resp.headers.setdefault(k, v)
        if request.url.path.startswith(("/api/", "/channels/")):
            resp.headers.setdefault("cache-control", "no-store")
        return resp

    origins = cors_origins()
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["content-type", "authorization"],
                           max_age=600)
