"""Typed configuration from environment variables (12-factor). Fails fast on unsafe production config."""
from __future__ import annotations
import os
from dataclasses import dataclass
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tigerkit import load_env  # noqa: E402


@dataclass(frozen=True)
class Settings:
    env: str
    signing_key: str
    session_ttl_hours: int
    rate_per_min: int
    rate_burst: int
    allow_registration: bool
    cookie_secure: bool
    adapters: str  # "sim" today; "live" requires real provider modules


def db_tls_problem(url: str) -> bool:
    """True when a remote DB URL would connect without full certificate + hostname verification."""
    from urllib.parse import parse_qs, urlsplit
    if not url:
        return False
    u = urlsplit(url)
    if u.hostname in (None, "localhost", "127.0.0.1", "::1", "db"):
        return False
    mode = os.environ.get("TIGER_DB_SSLMODE") or (parse_qs(u.query).get("sslmode") or [""])[0]
    return mode != "verify-full"


def get_settings() -> Settings:
    load_env()
    s = Settings(env=os.environ.get("WITNESS_ENV", "dev"),
                 signing_key=os.environ.get("WITNESS_SIGNING_KEY", ""),
                 session_ttl_hours=int(os.environ.get("WITNESS_SESSION_TTL_HOURS", "12")),
                 rate_per_min=int(os.environ.get("WITNESS_RATE_PER_MIN", "120")),
                 rate_burst=int(os.environ.get("WITNESS_RATE_BURST", "40")),
                 allow_registration=os.environ.get("WITNESS_ALLOW_REGISTRATION", "true").lower() == "true",
                 cookie_secure=os.environ.get("WITNESS_COOKIE_SECURE", "false").lower() == "true",
                 adapters=os.environ.get("WITNESS_ADAPTERS", "sim"))
    if s.env == "prod":
        if len(s.signing_key) < 32 or "change-me" in s.signing_key:
            raise SystemExit("WITNESS_SIGNING_KEY must be >= 32 random chars in prod")
        if not s.cookie_secure:
            raise SystemExit("WITNESS_COOKIE_SECURE must be true in prod")
        if db_tls_problem(os.environ.get("TIGER_DB_URL", "")):
            raise SystemExit("TIGER_DB_URL must use sslmode=verify-full in prod (or set TIGER_DB_SSLMODE=verify-full)")
    return s
