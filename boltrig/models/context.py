"""The invocation context that travels with every kernel call (S7.1).

Identity in the context is authenticated-by-construction (K-3): the kernel
stamps ``tenant_id`` / ``on_behalf_of`` from the verified bearer at the door;
they are never read from untrusted request fields by handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import RunId, TenantId, UserId, WorkspaceId
from .grants import EMPTY_GRANTS, GrantSet


@dataclass(frozen=True)
class InvocationContext:
    tenant_id: TenantId
    run_id: RunId | None = None
    parent_run_id: RunId | None = None
    depth: int = 0
    on_behalf_of: UserId | None = None  # delegated human identity (US-IAM-03)
    # The active WORKSPACE the caller is operating in ([2026] VJS-COUNTY 8, D4). The
    # ORGANISATION is the tenant boundary (tenant_id); a workspace is a scope INSIDE
    # it. Set from the session's active workspace only after the resolver has RE-
    # AUTHORIZED the caller's membership every request (fail-closed to None), so it
    # is never trusted from the client. Additive with a None default: this phase
    # PLUMBS it through the context; the next phase (D11) reads it to scope grants /
    # credentials / AI keys / workflows. None == no active workspace.
    workspace_id: WorkspaceId | None = None
    # Request provenance for the enriched audit row ([2026] VJS-COUNTY 9, D1/D2).
    # Stamped at the door from the request (the client peer / CF client header and
    # the User-Agent), never read from an untrusted body field by a handler. None
    # off the HTTP path (a fleet/internal call). Additive with None defaults.
    ip_address: str | None = None
    user_agent: str | None = None
    grants: GrantSet = field(default_factory=lambda: EMPTY_GRANTS)
    actor: str = "unknown"  # agent capability name or user id
    actor_tier: str = "ephemeral"  # tier1 | tier2 | ephemeral | human
    skills_loaded: tuple[str, ...] = ()
    # Arbitrary task context a skill may require (S7.5, e.g. epic_id, team_context).
    # The kernel dispatch never reads this; it carries skill-context for spawn-time
    # validation against a skill's context_requirements (US-SKL-01).
    extra: dict[str, Any] = field(default_factory=dict)


def context_to_envelope(ctx: InvocationContext) -> dict[str, Any]:
    """Serialise an :class:`InvocationContext` to a JSON-safe dict. A durable
    payload carries this envelope instead of the object so the queue (or a sealed
    held-call record) holds pure data.

    It lives beside the model rather than in one caller because THREE lanes now
    replay a context they did not build: the durable task bodies, the memory
    projection queue, and the held-write resume (decision 0018). A per-lane copy
    is how one lane silently drops an authority-bearing field - and the approval
    fingerprint binds most of these fields, so a dropped one is a resume that can
    never spend the approval it was created for."""
    return {
        "tenant_id": ctx.tenant_id,
        "run_id": ctx.run_id,
        "parent_run_id": ctx.parent_run_id,
        "depth": ctx.depth,
        "on_behalf_of": ctx.on_behalf_of,
        "workspace_id": ctx.workspace_id,
        "ip_address": ctx.ip_address,
        "user_agent": ctx.user_agent,
        "grants": {"allow": list(ctx.grants.allow), "deny": list(ctx.grants.deny)},
        "actor": ctx.actor,
        "actor_tier": ctx.actor_tier,
        "skills_loaded": list(ctx.skills_loaded),
        "extra": dict(ctx.extra),
    }


def context_from_envelope(env: dict[str, Any]) -> InvocationContext:
    """Reconstruct the :class:`InvocationContext` a replayed call re-enters the
    chokepoint with. The envelope only ever narrows to what it carries; missing
    fields take the fail-closed defaults (empty grants, ephemeral tier)."""
    grants = env.get("grants") or {}
    return InvocationContext(
        tenant_id=env["tenant_id"],
        run_id=env.get("run_id"),
        parent_run_id=env.get("parent_run_id"),
        depth=int(env.get("depth", 0)),
        on_behalf_of=env.get("on_behalf_of"),
        workspace_id=env.get("workspace_id"),
        ip_address=env.get("ip_address"),
        user_agent=env.get("user_agent"),
        grants=GrantSet.of(list(grants.get("allow") or []), list(grants.get("deny") or [])),
        actor=env.get("actor", "unknown"),
        actor_tier=env.get("actor_tier", "ephemeral"),
        skills_loaded=tuple(env.get("skills_loaded") or ()),
        extra=dict(env.get("extra") or {}),
    )
