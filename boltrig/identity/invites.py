"""Single-use invite tokens for first-party invite-only login ([2026] VJS-COUNTY 7).

The existing admin invite route pre-stages a role/scope in a ``UserInvitation``.
For first-party login (no external IdP) that invitation also carries a single-use
secret: the admin route mints one here, stores ONLY its sha256 (``token_hash``),
and shows the secret once. Accept-invite hashes the presented token, matches it,
and consumes the invitation atomically so a token works exactly once (D1).

Mirrors the SEC-34 PAT pattern: a random secret, hashed at rest, bounded by the
invitation's own ``expires_at``, revocable by the admin revoke route.
"""

from __future__ import annotations

import hashlib
import secrets

INVITE_PREFIX = "boltrig_invite_"


def generate_invite_token() -> str:
    """A fresh high-entropy single-use invite secret (shown once, never stored)."""
    return INVITE_PREFIX + secrets.token_urlsafe(32)


def hash_invite_token(secret: str) -> str:
    """The at-rest representation of an invite token: its sha256, never the secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def looks_like_invite_token(token: str) -> bool:
    """Cheap prefix check that a value is a Boltrig invite token."""
    return isinstance(token, str) and token.startswith(INVITE_PREFIX)
