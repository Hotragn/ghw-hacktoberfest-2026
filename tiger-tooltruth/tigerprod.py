"""Production helpers shared by every tiger-* service (copied verbatim, like tigerkit.py):
JSON structured logging, request ids, uniform error envelopes, token-bucket rate limiting,
checksum-tracked SQL migrations, scrypt password hashing and opaque session tokens."""

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
import uuid
from typing import Iterable, Sequence

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


# ------------------------------------------------------------------ logging
class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + f".{int(r.msecs):03d}Z",
             "level": r.levelname, "logger": r.name, "msg": r.getMessage(), "request_id": request_id_var.get()}
        for k, v in getattr(r, "extra_fields", {}).items():
            d[k] = v
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, default=str)


def setup_logging(level: str | None = None) -> None:
    """LOG_FORMAT=json (default in containers) or text; LOG_LEVEL=INFO."""
    h = logging.StreamHandler(sys.stdout)
    if os.environ.get("LOG_FORMAT", "json") == "json":
        h.setFormatter(JsonFormatter())
    else:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})


# ------------------------------------------------------------------ rate limiting
class RateLimiter:
    """In-process token bucket keyed by client. Good for a single replica; put Redis/edge limits in front
    when scaling horizontally (documented in SECURITY.md)."""

    def __init__(self, rate_per_min: float, burst: int):
        self.rate, self.burst, self.buckets = rate_per_min / 60.0, burst, {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        tokens, last = self.buckets.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.buckets[key] = (tokens, now)
            return False
        self.buckets[key] = (tokens - 1, now)
        if len(self.buckets) > 50_000:  # bound memory
            self.buckets.clear()
        return True


def install_http_hardening(app, service: str, limiter: RateLimiter | None = None,
                           exempt: Iterable[str] = ("/healthz", "/readyz")) -> None:
    """Request-id + access log middleware, rate limiting, security headers, JSON error envelopes."""
    from fastapi import Request
    from starlette.exceptions import HTTPException
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    log = logging.getLogger(service + ".http")
    exempt = set(exempt)

    @app.middleware("http")
    async def _mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        tok = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            client = request.client.host if request.client else "unknown"
            if limiter and request.url.path not in exempt and not limiter.allow(client):
                resp = JSONResponse({"error": {"code": "rate_limited", "message": "too many requests", "request_id": rid}},
                                    status_code=429, headers={"Retry-After": "10"})
            else:
                resp = await call_next(request)
        except Exception:  # noqa: BLE001 - last-resort guard, never leak internals
            log.exception("unhandled error")
            resp = JSONResponse({"error": {"code": "internal", "message": "internal error", "request_id": rid}},
                                status_code=500)
        resp.headers["x-request-id"] = rid
        resp.headers.setdefault("x-content-type-options", "nosniff")
        resp.headers.setdefault("x-frame-options", "DENY")
        resp.headers.setdefault("referrer-policy", "no-referrer")
        log_event(log, "request", path=request.url.path, method=request.method, status=resp.status_code,
                  ms=round((time.perf_counter() - t0) * 1000, 1))
        request_id_var.reset(tok)
        return resp

    @app.exception_handler(HTTPException)
    async def _http(request, exc: HTTPException):
        return JSONResponse({"error": {"code": "http_" + str(exc.status_code), "message": exc.detail,
                                       "request_id": request_id_var.get()}}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _val(request, exc: RequestValidationError):
        errs = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"error": {"code": "invalid_input", "message": "validation failed", "details": errs,
                                       "request_id": request_id_var.get()}}, status_code=422)


# ------------------------------------------------------------------ migrations
async def migrate(pool, schema: str, files: Sequence[str], repeatable: Iterable[str] = ()) -> list[str]:
    """Apply SQL files in order, once each, tracked in <schema>.schema_migrations with a sha256 checksum.
    Files named in `repeatable` (CREATE OR REPLACE function files) re-apply when their checksum changes.
    A changed checksum on a versioned file is an error: write a new migration instead.
    A Postgres advisory lock makes concurrent deploys safe."""
    log = logging.getLogger("migrate")
    repeatable, applied = set(repeatable), []
    async with pool.acquire() as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        await conn.execute(f"""CREATE TABLE IF NOT EXISTS {schema}.schema_migrations (
            name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())""")
        await conn.execute("SELECT pg_advisory_lock(hashtext($1))", schema + ".migrate")
        try:
            done = {r["name"]: r["checksum"] for r in await conn.fetch(f"SELECT name, checksum FROM {schema}.schema_migrations")}
            for f in files:
                name, sql = os.path.basename(f), open(f).read()
                cs = hashlib.sha256(sql.encode()).hexdigest()
                if done.get(name) == cs:
                    continue
                if name in done and name not in repeatable:
                    raise RuntimeError(f"migration {name} changed after being applied; add a new migration file")
                for stmt in sql.split("-- @@"):  # caggs cannot run in a transaction block
                    if stmt.strip():
                        await conn.execute(stmt)
                await conn.execute(f"""INSERT INTO {schema}.schema_migrations (name, checksum) VALUES ($1,$2)
                    ON CONFLICT (name) DO UPDATE SET checksum=EXCLUDED.checksum, applied_at=now()""", name, cs)
                log_event(log, "applied migration", name=name, schema=schema)
                applied.append(name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", schema + ".migrate")
    return applied


# ------------------------------------------------------------------ passwords + tokens
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:  # noqa: BLE001
        return False


def new_token() -> tuple[str, str]:
    """Returns (token for the client, sha256 to store). Only the hash ever touches the database."""
    t = secrets.token_urlsafe(32)
    return t, hashlib.sha256(t.encode()).hexdigest()


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def require_api_key_dependency(env_var: str, exempt: Iterable[str] = ("/", "/healthz", "/readyz")):
    """For single-tenant ops consoles (ToolTruth, ScamShield): if <env_var> is set, every non-exempt route needs
    `Authorization: Bearer <key>` or `X-API-Key: <key>`. Unset = open, allowed only outside prod
    (see `enforce_prod_config`)."""
    from fastapi import HTTPException, Request
    exempt = set(exempt)

    async def dep(request: Request):
        key = os.environ.get(env_var)
        if not key or request.url.path in exempt or request.url.path.startswith("/static"):
            return
        auth = request.headers.get("authorization") or ""
        got = request.headers.get("x-api-key") or (auth[7:] if auth.lower().startswith("bearer ") else None)
        if not got or not hmac.compare_digest(got.encode(), key.encode()):
            raise HTTPException(401, "missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})
    return dep


def enforce_prod_config(prefix: str) -> None:
    """<PREFIX>_ENV=prod requires <PREFIX>_API_KEY of >= 24 chars. Fail fast at import time."""
    if os.environ.get(f"{prefix}_ENV", "dev") == "prod":
        k = os.environ.get(f"{prefix}_API_KEY", "")
        if len(k) < 24:
            raise SystemExit(f"{prefix}_API_KEY (>= 24 chars) is required when {prefix}_ENV=prod")
    elif not os.environ.get(f"{prefix}_API_KEY"):
        logging.getLogger(prefix.lower()).warning("%s_API_KEY not set: API is open (dev only)", prefix)
