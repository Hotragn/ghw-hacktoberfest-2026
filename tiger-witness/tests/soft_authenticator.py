"""Software WebAuthn authenticator (ES256, 'none' attestation) for tests: produces the same JSON a browser's
navigator.credentials.create()/get() returns, so the server-side py_webauthn verification is exercised for real."""
import base64
import hashlib
import json
import os
import struct
import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftAuthenticator:
    def __init__(self, origin="http://localhost:8103", rp_id="localhost"):
        self.origin, self.rp_id = origin, rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.count = 0

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def _client(self, typ, challenge_b64u) -> bytes:
        return json.dumps({"type": typ, "challenge": challenge_b64u, "origin": self.origin, "crossOrigin": False}).encode()

    def create(self, options: dict) -> dict:
        pk = options["publicKey"] if "publicKey" in options else options
        assert pk["rp"]["id"] == self.rp_id
        cd = self._client("webauthn.create", pk["challenge"])
        att_cred = b"\x00" * 16 + struct.pack(">H", len(self.cred_id)) + self.cred_id + self._cose()
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x45]) + struct.pack(">I", self.count) + att_cred
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "attestationObject": b64u(att), "transports": ["internal"]},
                "clientExtensionResults": {}}

    def get(self, options: dict, tamper_challenge: bool = False) -> dict:
        pk = options["publicKey"] if "publicKey" in options else options
        ch = pk["challenge"]
        if tamper_challenge:
            ch = b64u(hashlib.sha256(b"other object").digest())
        self.count += 1
        cd = self._client("webauthn.get", ch)
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + struct.pack(">I", self.count)
        sig = self.key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "authenticatorData": b64u(auth), "signature": b64u(sig),
                             "userHandle": None}, "clientExtensionResults": {}}
