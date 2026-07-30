"""Ed25519 device-lease signing and opaque enrollment/session tokens."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import replace

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from boltrig.models.devices import DeviceLease

MAX_OPAQUE_TOKEN_BYTES = 4096


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            value + padding, altchars=b"-_", validate=True
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_base64url") from exc


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mint_scoped_token(kind: str, tenant_id: str, subject_id: str) -> str:
    payload = {
        "version": 1,
        "kind": kind,
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "secret": secrets.token_urlsafe(32),
    }
    return b64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def parse_scoped_token(value: str, kind: str) -> tuple[str, str]:
    if not value or len(value) > MAX_OPAQUE_TOKEN_BYTES:
        raise ValueError("invalid_scoped_token")
    try:
        payload = json.loads(b64url_decode(value))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_scoped_token") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or payload.get("kind") != kind
        or not isinstance(payload.get("tenant_id"), str)
        or not payload["tenant_id"]
        or not isinstance(payload.get("subject_id"), str)
        or not payload["subject_id"]
        or not isinstance(payload.get("secret"), str)
        or len(payload["secret"]) < 32
    ):
        raise ValueError("invalid_scoped_token")
    return payload["tenant_id"], payload["subject_id"]


class DeviceLeaseSigner:
    algorithm = "Ed25519"

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        public = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.public_key = b64url_encode(public)
        self.key_id = hashlib.sha256(public).hexdigest()

    @classmethod
    def from_seed(cls, seed: bytes) -> "DeviceLeaseSigner":
        if len(seed) != 32:
            raise ValueError("device lease signing seed must be 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    @classmethod
    def from_environment(cls) -> "DeviceLeaseSigner | None":
        encoded = os.environ.get("BOLTRIG_DEVICE_LEASE_SIGNING_KEY", "").strip()
        if not encoded:
            return None
        try:
            return cls.from_seed(b64url_decode(encoded))
        except ValueError:
            return None

    def sign(self, lease: DeviceLease) -> DeviceLease:
        unsigned = replace(lease, signing_key_id=self.key_id, signature="")
        signature = b64url_encode(self._private_key.sign(unsigned.canonical_bytes()))
        return replace(unsigned, signature=signature)

    def verify(self, lease: DeviceLease) -> bool:
        if lease.signing_key_id != self.key_id or not lease.signature:
            return False
        try:
            signature = b64url_decode(lease.signature)
            public = Ed25519PublicKey.from_public_bytes(
                b64url_decode(self.public_key)
            )
            public.verify(signature, replace(lease, signature="").canonical_bytes())
            return True
        except (ValueError, InvalidSignature):
            return False

    def verifier_view(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "public_key": self.public_key,
        }
