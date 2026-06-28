"""Personal access tokens (Round Four PAT, SEC-34).

A PAT lets a user drive the kernel from a non-interactive client (Claude Code, a
Teams agent, a script) over the same chokepoint, grants, HITL gating, rate limits
and audit as the site (SEC-37). Its authority is the intersection of its declared
scope and the owner's *current* grants, re-checked on every call: it can never
exceed the user, is bounded by a required expiry, is stored only as a hash, and is
revocable; a de-provisioned / deactivated user's tokens stop working (SEC-34).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from nankle.kernel.app import Principal
from nankle.models import GrantSet, PersonalAccessToken, utcnow

from .provisioning import current_grants_for_user

PAT_PREFIX = "nankle_pat_"
# A sane maximum lifetime (PAT-03: required, bounded expiry).
MAX_TTL_DAYS = 365
DEFAULT_TTL_DAYS = 90


def looks_like_pat(token: str) -> bool:
    """Whether a bearer value is a Nankle personal access token (cheap prefix)."""
    return token.startswith(PAT_PREFIX)


def hash_secret(secret: str) -> str:
    """The at-rest representation of a PAT: a SHA-256 hash, never the secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _generate_secret() -> str:
    return PAT_PREFIX + secrets.token_urlsafe(32)


def bounded_expiry(now: datetime, ttl_days: int | None) -> datetime:
    """Clamp a requested lifetime to (0, MAX_TTL_DAYS]; default if unset (PAT-03)."""
    days = ttl_days if ttl_days and ttl_days > 0 else DEFAULT_TTL_DAYS
    return now + timedelta(days=min(days, MAX_TTL_DAYS))


async def mint_pat(
    store,
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    requested_scope: list[str] | None,
    user_grants: GrantSet,
    ttl_days: int | None = None,
) -> tuple[PersonalAccessToken, str]:
    """Mint a PAT and return ``(record, secret)``; the secret is shown ONCE.

    The stored scope is the requested patterns the user's grants actually permit
    (or, if none requested, the user's own allow set) - so the token can never be
    minted above the user (SEC-34). The runtime re-check in
    ``resolve_pat_principal`` enforces the cap again at use time even if the user's
    grants later shrink.
    """
    requested = requested_scope if requested_scope else list(user_grants.allow)
    effective_scope = [p for p in requested if user_grants.permits_pattern(p)]
    secret = _generate_secret()
    now = utcnow()
    pat = PersonalAccessToken(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        name=name,
        token_hash=hash_secret(secret),
        scope=effective_scope,
        created_at=now,
        expires_at=bounded_expiry(now, ttl_days),
    )
    await store.add_pat(pat)
    return pat, secret


async def resolve_pat_principal(store, secret: str) -> Principal | None:
    """Resolve a PAT secret to a ``Principal``, or ``None`` if it is not usable.

    Fail-closed on: unknown / revoked / expired token, or a missing / deactivated
    owner (a de-provisioned user's tokens stop working). The effective grants are
    the PAT scope intersected with the owner's CURRENT grants - re-checked on every
    call, so the token never exceeds the user (SEC-34).
    """
    pat = await store.get_pat_by_hash(hash_secret(secret))
    if pat is None or pat.revoked:
        return None
    if pat.expires_at is not None and pat.expires_at <= utcnow():
        return None
    user = await store.get_user(pat.tenant_id, pat.user_id)
    if user is None or user.status != "active":
        return None  # de-provisioned / deactivated -> token stops working

    effective = GrantSet.of(allow=list(pat.scope)).intersect(current_grants_for_user(user))

    pat.last_used_at = utcnow()
    await store.update_pat(pat)

    return Principal(
        tenant_id=pat.tenant_id,
        subject=user.id,
        grants=effective,
        role=user.role,
        actor_tier="human",
        scope=user.scope,
    )
