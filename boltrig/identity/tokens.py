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
from typing import Any

from boltrig.kernel.app import Principal
from boltrig.models import GrantSet, PersonalAccessToken, utcnow

from .provisioning import effective_grants_for_request
from .sessions import resolve_active_workspace

PAT_PREFIX = "boltrig_pat_"
# A sane maximum lifetime (PAT-03: required, bounded expiry).
MAX_TTL_DAYS = 365
DEFAULT_TTL_DAYS = 90


def looks_like_pat(token: str) -> bool:
    """Whether a bearer value is a Boltrig personal access token (cheap prefix)."""
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
    store: Any,
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


class WorkspaceNotPermitted(Exception):
    """A bearer named a workspace its owner is not a member of."""

    def __init__(self, workspace_id: str) -> None:
        super().__init__("not a member of that workspace")
        self.workspace_id = workspace_id


async def _pat_active_workspace(
    store: Any, tenant_id: str, user_id: str, requested_workspace_id: str | None
) -> str | None:
    """Which workspace this bearer is acting in.

    A PAT carries no session and so no active workspace, which leaves a
    PAT-driven chat turn unscoped and degrades the read-only Codex phase
    (no_read_only_phase_scope). Two ways to get one:

    REQUESTED. The caller names it, and it goes through
    ``resolve_active_workspace`` - the SAME re-check the session path runs on
    every request - rather than a second membership test that could drift from
    it. A workspace the owner cannot reach raises rather than returning None,
    because None means "no active workspace" and that yields the owner's org
    grants UN-NARROWED. Falling back would answer an out-of-reach request by
    widening authority.

    INFERRED. With exactly one membership the choice is unambiguous, so bind it.
    With zero or many it stays None, fail-closed, which is what it did before a
    caller could ask.
    """
    if requested_workspace_id:
        active = await resolve_active_workspace(
            store, tenant_id, user_id, requested_workspace_id
        )
        if active is None:
            raise WorkspaceNotPermitted(requested_workspace_id)
        return active
    workspaces = await store.list_workspaces_for_user(tenant_id, user_id)
    return workspaces[0].id if len(workspaces) == 1 else None


async def resolve_pat_principal(
    store: Any, secret: str, *, requested_workspace_id: str | None = None
) -> Principal | None:
    """Resolve a PAT secret to a ``Principal``, or ``None`` if it is not usable.

    Fail-closed on: unknown / revoked / expired token, or a missing / deactivated
    owner (a de-provisioned user's tokens stop working). The effective grants are
    the PAT scope intersected with the owner's CURRENT grants - re-checked on every
    call, so the token never exceeds the user (SEC-34).

    ``requested_workspace_id`` lets a headless caller say WHICH workspace it is
    acting in, which a PAT could not do before: the session routes that switch an
    active context refuse a bearer outright, so a user who belongs to two
    workspaces had no way to select one and every PAT call ran unscoped. An
    embedded console (Opbox Agents) needs exactly this, and so does a per-workspace
    agent roster.

    A REQUESTED WORKSPACE THAT FAILS MEMBERSHIP REFUSES THE CALL. It does not fall
    back to None, and the direction matters: with no active workspace
    ``effective_grants_for_request`` returns the owner's org grants UN-NARROWED, so
    a silent fallback would answer a request for a workspace the caller cannot
    reach by WIDENING their authority. Refusing is the only fail-closed answer.
    """
    pat = await store.get_pat_by_hash(hash_secret(secret))
    if pat is None or pat.revoked:
        return None
    if pat.expires_at is not None and pat.expires_at <= utcnow():
        return None
    # RLS-live: the PAT table is the one cross-tenant lookup (it resolves the
    # tenant from the hash). Once the tenant is known, bind it BEFORE the
    # RLS-scoped users read below, or the _RlsPool sees a null GUC and the owner
    # read fails closed - a valid token would 401 as "de-provisioned". No-op for
    # the in-memory store and when RLS is off.
    from boltrig.store.postgres import set_current_tenant

    set_current_tenant(pat.tenant_id)
    user = await store.get_user(pat.tenant_id, pat.user_id)
    if user is None or user.status != "active":
        return None  # de-provisioned / deactivated -> token stops working

    active_workspace_id = await _pat_active_workspace(
        store, pat.tenant_id, user.id, requested_workspace_id
    )

    # SEC-34 / SEC-109. The grants are narrowed by the ACTIVE WORKSPACE's role
    # ceiling, exactly as the session path does (identity/sessions.py). Until
    # 2026-07-26 this line read ``current_grants_for_user(user)`` - the ORG grants,
    # un-narrowed - while the block above bound an active workspace anyway, on the
    # reasoning that "they are a member, so this confers nothing new". Membership
    # as a VIEWER confers less, and that was the hole: a user who is a viewer in
    # their only workspace was refused a write verb through the browser session and
    # granted it through a PAT, in the same workspace, on the same account. The
    # workspace ceiling was enforced on the cookie path and not on the bearer path,
    # so minting a token from the documented POST /v1/me/tokens route escalated.
    #
    # It survived because the workspace-grant tests bind SEC-108/109/110 directly at
    # effective_grants_for_request and narrow_grants_to_workspace, and never drive a
    # PAT - a control tested at the function it lives in, on the one path that did
    # not call it.
    user_grants = await effective_grants_for_request(store, user, active_workspace_id)
    effective = GrantSet.of(allow=list(pat.scope)).intersect(user_grants)

    pat.last_used_at = utcnow()
    await store.update_pat(pat)

    return Principal(
        tenant_id=pat.tenant_id,
        subject=user.id,
        grants=effective,
        role=user.role,
        actor_tier="human",
        scope=user.scope,
        active_workspace_id=active_workspace_id,
        # Acts with its owner's authority, but nobody is at a keyboard.
        credential_kind="pat",
    )
