"""Consent: scoped, expiring, revocable grants per tool pattern + data class, and the human approval inbox."""
from __future__ import annotations
import fnmatch
import json
import uuid
from datetime import datetime, timedelta, timezone

SCOPES = ("read", "write", "spend")


def _row(r) -> dict:
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    for k in ("args", "reasons", "passkey_assertion"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    return d


async def create_grant(conn, user: str, tool_pattern: str, scopes: list[str], data_classes: list[str],
                       ttl_hours: float, auto_approve: bool = False, max_uses: int | None = None, note: str | None = None) -> dict:
    if not scopes or not set(scopes) <= set(SCOPES):
        raise ValueError(f"scopes must be among {SCOPES}")
    if not 0 < ttl_hours <= 24 * 365:
        raise ValueError("ttl_hours must be in (0, 8760]")
    r = await conn.fetchrow("""INSERT INTO grants (grant_id,user_id,tool_pattern,scopes,data_classes,auto_approve,max_uses,expires_at,note)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""", uuid.uuid4(), user, tool_pattern, scopes, data_classes,
        auto_approve, max_uses, datetime.now(timezone.utc) + timedelta(hours=ttl_hours), note)
    return _row(r)


async def list_grants(conn, user: str) -> list[dict]:
    return [_row(r) for r in await conn.fetch("SELECT * FROM grants WHERE user_id=$1 ORDER BY created_at DESC", user)]


async def revoke_grant(conn, user: str, grant_id: str) -> bool:
    return bool(await conn.fetchval("""UPDATE grants SET revoked_at=now() WHERE grant_id=$1 AND user_id=$2
        AND revoked_at IS NULL RETURNING grant_id""", uuid.UUID(grant_id), user))


async def find_grant(conn, user: str, tool: str, scope: str, data_class: str) -> dict | None:
    rs = await conn.fetch("""SELECT * FROM grants WHERE user_id=$1 AND revoked_at IS NULL AND expires_at > now()
        AND $2 = ANY(scopes) AND $3 = ANY(data_classes) AND (max_uses IS NULL OR uses < max_uses)
        ORDER BY auto_approve DESC, expires_at""", user, scope, data_class)
    for r in rs:
        if fnmatch.fnmatchcase(tool, r["tool_pattern"]):
            return _row(r)
    return None


async def consume_grant(conn, grant_id: str) -> None:
    await conn.execute("UPDATE grants SET uses = uses + 1 WHERE grant_id=$1", uuid.UUID(grant_id))


async def park(conn, user: str, task_id: uuid.UUID, call_id: str, tool: str, args: dict, reasons: list,
               ttl_hours: float = 48, risk: str = "normal") -> dict:
    r = await conn.fetchrow("""INSERT INTO pending_approvals (approval_id,user_id,task_id,call_id,tool,args,reasons,expires_at,risk)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9) RETURNING *""", uuid.uuid4(), user, task_id, call_id, tool,
        json.dumps(args), json.dumps(reasons), datetime.now(timezone.utc) + timedelta(hours=ttl_hours), risk)
    return _row(r)


async def list_approvals(conn, user: str, status: str | None = "pending") -> list[dict]:
    await conn.execute("""UPDATE pending_approvals SET status='expired' WHERE user_id=$1 AND status='pending'
        AND expires_at < now()""", user)
    q = "SELECT * FROM pending_approvals WHERE user_id=$1" + (" AND status=$2" if status else "") + " ORDER BY created_at DESC LIMIT 100"
    return [_row(r) for r in await conn.fetch(q, *([user, status] if status else [user]))]


def approval_sha256(a: dict) -> str:
    """Hash of exactly what the user is approving (bound into the passkey challenge)."""
    from witness.passkeys import canonical_sha256
    return canonical_sha256({"approval_id": str(a["approval_id"]), "tool": a["tool"],
                             "args": a["args"] if isinstance(a["args"], dict) else json.loads(a["args"])})


async def get_pending(conn, user: str, approval_id: str) -> dict | None:
    r = await conn.fetchrow("""SELECT * FROM pending_approvals WHERE approval_id=$1 AND user_id=$2 AND status='pending'
        AND expires_at > now()""", uuid.UUID(approval_id), user)
    return _row(r) if r else None


async def decide(conn, user: str, approval_id: str, approve: bool, passkey_evidence: dict | None = None) -> dict | None:
    r = await conn.fetchrow("""UPDATE pending_approvals SET status=$3, decided_at=now(), passkey_assertion=$4::jsonb
        WHERE approval_id=$1 AND user_id=$2 AND status='pending' AND expires_at > now() RETURNING *""", uuid.UUID(approval_id), user,
        "approved" if approve else "denied", json.dumps(passkey_evidence) if passkey_evidence else None)
    return _row(r) if r else None
