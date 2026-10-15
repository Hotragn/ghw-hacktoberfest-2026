"""WebAuthn passkeys (py_webauthn) as the user's trusted surface.

Authorising a payment mandate or a high-risk approval is a WebAuthn *assertion* whose challenge is derived from the
exact object being authorised:  challenge = SHA-256("witness|<purpose>|<object sha256>|<nonce>").
The authenticator signs clientDataJSON (which contains that challenge), so the signature is bound to the mandate /
approval contents and is useless for anything else. The full assertion is stored next to the object, so a bank,
merchant or auditor can verify it offline with the credential's public key, without trusting this server."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)


class PasskeyError(ValueError):
    pass


class PasskeyRequired(PermissionError):
    pass


def rp_id() -> str:
    return os.environ.get("WITNESS_RP_ID", "localhost")


def origins() -> list[str]:
    return [o.strip() for o in os.environ.get("WITNESS_ORIGIN", "http://localhost:8103").split(",") if o.strip()]


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def bound_challenge(purpose: str, bound_sha256: str, nonce: bytes) -> bytes:
    return hashlib.sha256(f"witness|{purpose}|{bound_sha256}|".encode() + nonce).digest()


async def has_passkey(conn, user: str) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM webauthn_credentials WHERE user_id=$1 LIMIT 1", user))


async def list_passkeys(conn, user: str) -> list[dict]:
    rs = await conn.fetch("SELECT credential_id, name, created_at, last_used_at, sign_count FROM webauthn_credentials WHERE user_id=$1", user)
    return [{"id": b64u(r["credential_id"]), "name": r["name"], "created_at": r["created_at"].isoformat(),
             "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None} for r in rs]


async def _store_challenge(conn, user, purpose, challenge, subject_id=None, bound=None) -> uuid.UUID:
    cid = uuid.uuid4()
    await conn.execute("""INSERT INTO webauthn_challenges (challenge_id,user_id,purpose,subject_id,bound_sha256,challenge,expires_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7)""", cid, user, purpose, subject_id, bound, challenge,
                       datetime.now(timezone.utc) + timedelta(minutes=5))
    return cid


async def _take_challenge(conn, user, challenge_id: str, purpose: str):
    r = await conn.fetchrow("""UPDATE webauthn_challenges SET used_at=now() WHERE challenge_id=$1 AND user_id=$2 AND purpose=$3
        AND used_at IS NULL AND expires_at > now() RETURNING *""", uuid.UUID(challenge_id), user, purpose)
    if not r:
        raise PasskeyError("challenge unknown, expired or already used")
    return r


async def begin_registration(conn, user: str, user_name: str, display: str) -> dict:
    existing = await conn.fetch("SELECT credential_id FROM webauthn_credentials WHERE user_id=$1", user)
    opts = generate_registration_options(
        rp_id=rp_id(), rp_name="Witness", user_name=user_name, user_id=user.encode(), user_display_name=display,
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED,
                                                               user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=r["credential_id"]) for r in existing])
    cid = await _store_challenge(conn, user, "register", opts.challenge)
    return {"challenge_id": str(cid), "publicKey": json.loads(options_to_json(opts))}


async def finish_registration(conn, user: str, challenge_id: str, credential: dict, name: str = "passkey") -> dict:
    ch = await _take_challenge(conn, user, challenge_id, "register")
    try:
        v = verify_registration_response(credential=credential, expected_challenge=ch["challenge"], expected_rp_id=rp_id(),
                                         expected_origin=origins(), require_user_verification=True)
    except Exception as e:
        raise PasskeyError(f"registration rejected: {e}") from None
    await conn.execute("""INSERT INTO webauthn_credentials (credential_id,user_id,public_key,sign_count,name,transports)
        VALUES ($1,$2,$3,$4,$5,$6)""", v.credential_id, user, v.credential_public_key, v.sign_count, name[:60],
                       list(credential.get("response", {}).get("transports") or []))
    return {"id": b64u(v.credential_id), "name": name}


async def begin_assertion(conn, user: str, purpose: str, subject_id: str, bound_sha256: str) -> dict:
    creds = await conn.fetch("SELECT credential_id FROM webauthn_credentials WHERE user_id=$1", user)
    if not creds:
        raise PasskeyError("no passkey registered")
    nonce = secrets.token_bytes(16)
    challenge = bound_challenge(purpose, bound_sha256, nonce)
    opts = generate_authentication_options(rp_id=rp_id(), challenge=challenge,
                                           allow_credentials=[PublicKeyCredentialDescriptor(id=r["credential_id"]) for r in creds],
                                           user_verification=UserVerificationRequirement.REQUIRED)
    cid = await _store_challenge(conn, user, purpose, nonce, subject_id, bound_sha256)  # store nonce; challenge is derived
    return {"challenge_id": str(cid), "bound_sha256": bound_sha256, "nonce": b64u(nonce),
            "publicKey": json.loads(options_to_json(opts))}


async def finish_assertion(conn, user: str, challenge_id: str, credential: dict, purpose: str, subject_id: str,
                           current_bound_sha256: str) -> dict:
    ch = await _take_challenge(conn, user, challenge_id, purpose)
    if ch["subject_id"] != subject_id or ch["bound_sha256"] != current_bound_sha256:
        raise PasskeyError("the object changed after the challenge was issued")
    cred_id = unb64u(credential.get("rawId") or credential.get("id", ""))
    row = await conn.fetchrow("SELECT * FROM webauthn_credentials WHERE credential_id=$1 AND user_id=$2", cred_id, user)
    if not row:
        raise PasskeyError("unknown credential")
    expected = bound_challenge(purpose, current_bound_sha256, ch["challenge"])
    try:
        v = verify_authentication_response(credential=credential, expected_challenge=expected, expected_rp_id=rp_id(),
                                           expected_origin=origins(), credential_public_key=row["public_key"],
                                           credential_current_sign_count=row["sign_count"], require_user_verification=True)
    except Exception as e:
        raise PasskeyError(f"assertion rejected: {e}") from None
    await conn.execute("UPDATE webauthn_credentials SET sign_count=$2, last_used_at=now() WHERE credential_id=$1",
                       cred_id, v.new_sign_count)
    r = credential["response"]
    return {"credential_id": b64u(cred_id), "public_key_cose": b64u(row["public_key"]), "rp_id": rp_id(),
            "purpose": purpose, "subject_id": subject_id, "bound_sha256": current_bound_sha256, "nonce": b64u(ch["challenge"]),
            "authenticatorData": r["authenticatorData"], "clientDataJSON": r["clientDataJSON"], "signature": r["signature"],
            "verified_at": datetime.now(timezone.utc).isoformat()}


def verify_evidence(ev: dict) -> bool:
    """Offline check of a stored assertion: binding (challenge derives from the object hash) + signature."""
    client = json.loads(unb64u(ev["clientDataJSON"]))
    expected = bound_challenge(ev["purpose"], ev["bound_sha256"], unb64u(ev["nonce"]))
    if unb64u(client["challenge"]) != expected:
        return False
    try:
        verify_authentication_response(
            credential={"id": ev["credential_id"], "rawId": ev["credential_id"], "type": "public-key",
                        "response": {"authenticatorData": ev["authenticatorData"], "clientDataJSON": ev["clientDataJSON"],
                                     "signature": ev["signature"]}},
            expected_challenge=expected, expected_rp_id=ev["rp_id"], expected_origin=client["origin"],
            credential_public_key=unb64u(ev["public_key_cose"]), credential_current_sign_count=0, require_user_verification=True)
        return True
    except Exception:
        return False
