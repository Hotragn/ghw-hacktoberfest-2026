"""Agent payments, modelled on AP2 v0.2: the user authorises an OPEN mandate (constraints: merchant allowlist,
per-transaction cap, rolling budget, expiry) on a trusted surface (an authenticated session); the agent then
assembles a CLOSED checkout+payment mandate bound to a merchant checkout by SHA-256 hash and signs it with its own
ECDSA P-256 key (non-deterministic signatures, as AP2 requires). Enforcement runs in code before any rail is called.
Rails: MockRail (tests/dev) and StripeRail (PaymentIntents, enabled by STRIPE_API_KEY)."""
from __future__ import annotations
import base64
import fnmatch
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from witness.agent import signing_key


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def _agent_key() -> ec.EllipticCurvePrivateKey:
    """Deterministically derived from WITNESS_SIGNING_KEY so the public key is stable across restarts with no
    extra secret to store; set WITNESS_AGENT_KEY_PEM to use an HSM/KMS-exported key instead."""
    pem = os.environ.get("WITNESS_AGENT_KEY_PEM")
    if pem:
        return serialization.load_pem_private_key(pem.encode(), password=None)
    n = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
    d = int.from_bytes(hmac.new(signing_key(), b"witness-agent-key-v1", hashlib.sha256).digest(), "big") % (n - 1) + 1
    return ec.derive_private_key(d, ec.SECP256R1())


def agent_public_pem() -> str:
    return _agent_key().public_key().public_bytes(serialization.Encoding.PEM,
                                                 serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def agent_sign(obj) -> str:
    return base64.urlsafe_b64encode(_agent_key().sign(canonical(obj), ec.ECDSA(hashes.SHA256()))).decode()


def agent_verify(obj, sig: str, public_pem: str | None = None) -> bool:
    pub = serialization.load_pem_public_key((public_pem or agent_public_pem()).encode())
    try:
        pub.verify(base64.urlsafe_b64decode(sig), canonical(obj), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


def surface_sign(obj) -> str:
    """Trusted-surface authorisation of an open mandate (server HMAC, issued only from an authenticated session)."""
    return hmac.new(signing_key(), b"open-mandate|" + canonical(obj), hashlib.sha256).hexdigest()


class PaymentError(ValueError):
    pass


@dataclass
class RailResult:
    ok: bool
    provider_ref: str
    status: str
    detail: dict


class PaymentRail(Protocol):
    name: str

    async def charge(self, amount: Decimal, currency: str, merchant: str, idempotency_key: str, meta: dict) -> RailResult: ...


class MockRail:
    name = "mock"

    def __init__(self):
        self.charges: dict[str, RailResult] = {}

    async def charge(self, amount, currency, merchant, idempotency_key, meta):
        if idempotency_key not in self.charges:
            self.charges[idempotency_key] = RailResult(True, "mock_" + idempotency_key[:12], "settled",
                                                       {"amount": str(amount), "merchant": merchant})
        return self.charges[idempotency_key]


class StripeRail:
    """Creates and confirms a PaymentIntent against a saved customer payment method (off_session)."""
    name = "stripe"

    def __init__(self, api_key: str, customer: str, payment_method: str, transport=None):
        self.key, self.customer, self.pm = api_key, customer, payment_method
        self.client = httpx.AsyncClient(base_url="https://api.stripe.com", timeout=30, transport=transport)

    async def charge(self, amount, currency, merchant, idempotency_key, meta):
        data = {"amount": str(int((amount * 100).to_integral_value())), "currency": currency.lower(),
                "customer": self.customer, "payment_method": self.pm, "confirm": "true", "off_session": "true",
                "description": f"Witness agent purchase at {merchant}"[:200]}
        for k, v in meta.items():
            data[f"metadata[{k}]"] = str(v)[:400]
        r = await self.client.post("/v1/payment_intents", data=data, auth=(self.key, ""),
                                   headers={"Idempotency-Key": idempotency_key})
        j = r.json()
        if r.status_code >= 400:
            return RailResult(False, j.get("error", {}).get("payment_intent", {}).get("id", ""), "failed", j.get("error", {}))
        return RailResult(j.get("status") == "succeeded", j["id"], "settled" if j.get("status") == "succeeded" else "pending",
                          {"status": j.get("status")})


def rail_from_env() -> PaymentRail:
    k = os.environ.get("STRIPE_API_KEY")
    if k:
        return StripeRail(k, os.environ["STRIPE_CUSTOMER_ID"], os.environ["STRIPE_PAYMENT_METHOD_ID"])
    return MockRail()


def merchant_allowed(merchant: str, allow: list[str]) -> bool:
    m = merchant.lower().strip()
    for a in allow:
        a = a.lower().strip()
        if m == a or (a.startswith("*.") and (m.endswith(a[1:]) or m == a[2:])) or (a != "*" and fnmatch.fnmatchcase(m, a)):
            return True
    return False


def _row(r) -> dict:
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, timedelta):
            d[k] = v.total_seconds()
        elif k in ("content", "checkout", "closed_mandate", "passkey_assertion") and isinstance(v, str):
            d[k] = json.loads(v)
    return d


async def create_open_mandate(conn, user: str, description: str, merchants: list[str], max_per_txn: float,
                              budget: float, ttl_days: float = 30, currency: str = "USD", window_days: int = 30,
                              human_present_required: bool = False, passkey_required: bool = False) -> dict:
    if not merchants or any(m.strip() in ("", "*") for m in merchants):
        raise PaymentError("an explicit merchant allowlist is required (no bare '*')")
    if max_per_txn <= 0 or budget <= 0 or max_per_txn > budget:
        raise PaymentError("need 0 < max_per_txn <= budget")
    mid = "pm-" + uuid.uuid4().hex[:16]
    exp = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    content = {"type": "open_checkout_payment_mandate", "ap2_model": "v0.2-open", "mandate_id": mid, "user_id": user,
               "description": description, "merchants": sorted(m.lower() for m in merchants), "currency": currency,
               "max_per_txn": f"{max_per_txn:.2f}", "budget": f"{budget:.2f}", "budget_window_days": window_days,
               "human_present_required": human_present_required, "passkey_required": passkey_required, "exp": exp.isoformat(),
               "cnf": {"agent_public_key_sha256": hashlib.sha256(agent_public_pem().encode()).hexdigest()}}
    r = await conn.fetchrow("""INSERT INTO pay_mandates (mandate_id,user_id,description,merchants,currency,max_per_txn,budget,
        budget_window,human_present_required,content,user_signature,expires_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,make_interval(days=>$8),$9,$10::jsonb,$11,$12) RETURNING *""",
        mid, user, description, content["merchants"], currency, Decimal(content["max_per_txn"]), Decimal(content["budget"]),
        window_days, human_present_required, json.dumps(content), surface_sign(content), exp)
    return _row(r)


async def list_mandates(conn, user: str) -> list[dict]:
    out = []
    for r in await conn.fetch("SELECT * FROM pay_mandates WHERE user_id=$1 ORDER BY created_at DESC", user):
        d = _row(r)
        d["spent_in_window"] = float(await conn.fetchval("""SELECT coalesce(sum(amount),0) FROM payments WHERE mandate_id=$1
            AND status <> 'failed' AND ts > now() - $2::interval""", r["mandate_id"], r["budget_window"]))
        out.append(d)
    return out


async def revoke_mandate(conn, user: str, mandate_id: str) -> bool:
    return bool(await conn.fetchval("""UPDATE pay_mandates SET revoked_at=now() WHERE mandate_id=$1 AND user_id=$2
        AND revoked_at IS NULL RETURNING mandate_id""", mandate_id, user))


async def check(conn, user: str, merchant: str, amount: Decimal, currency: str) -> tuple[dict | None, list[dict]]:
    """Find an open mandate that covers this purchase. Returns (mandate, reasons). Pure enforcement, no side effects."""
    reasons, chosen = [], None
    for r in await conn.fetch("""SELECT * FROM pay_mandates WHERE user_id=$1 AND revoked_at IS NULL AND expires_at > now()
        AND currency=$2 ORDER BY max_per_txn""", user, currency):
        if surface_sign(json.loads(r["content"])) != r["user_signature"]:
            reasons.append({"mandate": r["mandate_id"], "fail": "mandate signature invalid (tampered)"})
            continue
        if json.loads(r["content"]).get("passkey_required") and not r["passkey_confirmed_at"]:
            reasons.append({"mandate": r["mandate_id"], "fail": "mandate awaiting your passkey confirmation"})
            continue
        if not merchant_allowed(merchant, list(r["merchants"])):
            reasons.append({"mandate": r["mandate_id"], "fail": f"merchant {merchant} not in allowlist"})
            continue
        if amount > r["max_per_txn"]:
            reasons.append({"mandate": r["mandate_id"], "fail": f"{amount} exceeds per-transaction cap {r['max_per_txn']}"})
            continue
        spent = await conn.fetchval("""SELECT coalesce(sum(amount),0) FROM payments WHERE mandate_id=$1 AND status <> 'failed'
            AND ts > now() - $2::interval""", r["mandate_id"], r["budget_window"])
        if spent + amount > r["budget"]:
            reasons.append({"mandate": r["mandate_id"], "fail": f"budget exhausted ({spent} + {amount} > {r['budget']})"})
            continue
        chosen = _row(r)
        chosen["spent_in_window"] = float(spent)
        reasons.append({"mandate": r["mandate_id"], "ok": "within allowlist, per-txn cap and budget"})
        break
    if not chosen and not reasons:
        reasons.append({"fail": "no active payment mandate for this currency"})
    return chosen, reasons


async def execute(conn, rail: PaymentRail, user: str, mandate: dict, merchant: str, amount: Decimal, currency: str,
                  items: list | None, idempotency_key: str) -> dict:
    """Assemble the closed checkout + payment mandate, sign it with the agent key, charge the rail, record it.
    Serialised per mandate (advisory lock) so concurrent tasks cannot overspend the budget."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "pay:" + mandate["mandate_id"])
    prior = await conn.fetchrow("SELECT * FROM payments WHERE idempotency_key=$1", idempotency_key)
    if prior:
        return _row(prior)
    again, _ = await check(conn, user, merchant, amount, currency)  # re-check under the lock
    if not again or again["mandate_id"] != mandate["mandate_id"]:
        raise PaymentError("mandate no longer covers this purchase")
    checkout = {"merchant": merchant.lower(), "items": items or [], "total": f"{amount:.2f}", "currency": currency,
                "created": datetime.now(timezone.utc).isoformat(), "nonce": uuid.uuid4().hex}
    chash = hashlib.sha256(canonical(checkout)).hexdigest()
    closed = {"type": "closed_checkout_payment_mandate", "open_mandate_id": mandate["mandate_id"],
              "open_mandate_sha256": hashlib.sha256(canonical(mandate["content"])).hexdigest(),
              "checkout_hash": chash, "amount": f"{amount:.2f}", "currency": currency, "payee": merchant.lower(),
              "human_present": False, "iat": datetime.now(timezone.utc).isoformat()}
    sig = agent_sign(closed)
    res = await rail.charge(amount, currency, merchant, idempotency_key,
                            {"mandate_id": mandate["mandate_id"], "checkout_hash": chash})
    r = await conn.fetchrow("""INSERT INTO payments (payment_id,user_id,mandate_id,merchant,amount,currency,checkout,checkout_hash,
        closed_mandate,agent_signature,rail,provider_ref,status,idempotency_key)
        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9::jsonb,$10,$11,$12,$13,$14) RETURNING *""", uuid.uuid4(), user,
        mandate["mandate_id"], merchant.lower(), amount, currency, json.dumps(checkout), chash, json.dumps(closed), sig,
        rail.name, res.provider_ref, res.status if res.ok or res.status != "settled" else "failed", idempotency_key)
    return _row(r)


def mandate_sha256(content: dict) -> str:
    return hashlib.sha256(canonical(content)).hexdigest()


async def confirm_with_passkey(conn, user: str, mandate_id: str, evidence: dict) -> dict:
    r = await conn.fetchrow("""UPDATE pay_mandates SET passkey_assertion=$3::jsonb, passkey_confirmed_at=now()
        WHERE mandate_id=$1 AND user_id=$2 AND revoked_at IS NULL RETURNING *""", mandate_id, user, json.dumps(evidence))
    if not r:
        raise PaymentError("no active mandate with that id")
    return _row(r)
