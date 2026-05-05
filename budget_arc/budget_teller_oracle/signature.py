from __future__ import annotations

import base64
import hashlib
from binascii import Error as BinasciiError

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _decode_loose(value: str) -> bytes:
    cleaned = value.strip()
    if cleaned.startswith("ed25519:"):
        cleaned = cleaned.split(":", 1)[1]

    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        pass

    padded = cleaned + ("=" * ((4 - len(cleaned) % 4) % 4))
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(padded)
        except (BinasciiError, ValueError):
            continue
    raise ValueError("Unsupported encoded key/signature format")


def load_ed25519_public_key(encoded_key: str) -> Ed25519PublicKey:
    value = encoded_key.strip()
    if "BEGIN PUBLIC KEY" in value:
        public_key = serialization.load_pem_public_key(value.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("TELLER_SIGNING_PUBLIC_KEY is not an Ed25519 public key")
        return public_key

    raw = _decode_loose(value)
    if len(raw) != 32:
        raise ValueError("TELLER_SIGNING_PUBLIC_KEY must decode to a 32-byte Ed25519 key")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_teller_enrollment_signature(
    *,
    signing_public_key: str,
    signatures: list[str],
    nonce: str,
    access_token: str,
    user_id: str,
    enrollment_id: str,
    environment: str,
) -> bool:
    if not signatures:
        return False

    public_key = load_ed25519_public_key(signing_public_key)
    message = f"{nonce}.{access_token}.{user_id}.{enrollment_id}.{environment}".encode("utf-8")
    digest = hashlib.sha256(message).digest()

    for encoded_signature in signatures:
        signature = _decode_loose(encoded_signature)
        for candidate in (digest, message):
            try:
                public_key.verify(signature, candidate)
                return True
            except InvalidSignature:
                continue
    return False

