"""Which workspace an agent-capability mutation targets, and who may target it.

One derivation, three consumers: the two approval-context builders and the
executor. If the fingerprint were computed against one row and the write landed
on another, an approval minted for one workspace's ``researcher`` could be spent
editing a different workspace's ``researcher`` - and since 0083 made the name
unique only WITHIN a scope, that is no longer a hypothetical.

The authority rule (decided with the Principal, 2026-08-19):

  org scope (``context.workspace_id is None``)
      manages org-wide profiles, and any workspace's by naming it in
      ``params["workspace_id"]``.
  inside a workspace (``context.workspace_id`` set)
      manages ONLY that workspace's profiles. An omitted ``workspace_id``
      means "mine", not "org-wide", and naming a different one is refused.
  member / agent / viewer
      already denied the whole ``control.*`` namespace by
      ``WORKSPACE_ROLE_CEILINGS`` ([2026] VJS-COUNTY 8, D11), so they never
      reach here.

THIS NARROWS AN AUTHORITY THAT EXISTS TODAY. ``WORKSPACE_ROLE_CEILINGS`` denies
a workspace admin only ``control.workspace.*``, so before 0083 a workspace admin
could edit an agent profile the whole organisation sees. Nobody noticed because
there was no second workspace for it to matter in. A caller who relied on that
now gets a 403 and must do the edit at org scope.
"""

from __future__ import annotations

from typing import Any, Iterable

from boltrig.models import AdapterFailure, AgentCapability, InvocationContext

WORKSPACE_SCOPE_FORBIDDEN = "workspace_scope_forbidden"


def resolve_capability_scope(
    params: dict[str, Any], context: InvocationContext
) -> str | None:
    """The workspace a mutation targets, or ``None`` for the org-wide scope."""
    raw = params.get("workspace_id")
    requested = str(raw).strip() or None if raw is not None else None
    if context.workspace_id is None:
        return requested
    if requested is not None and requested != context.workspace_id:
        raise AdapterFailure(
            "a caller operating inside a workspace may only author agent "
            "profiles in that workspace",
            status_code=403,
            reason=WORKSPACE_SCOPE_FORBIDDEN,
        )
    # An omitted workspace_id inside a workspace means THIS workspace. It must
    # not fall back to the org-wide scope: that fallback is precisely the
    # authority being withdrawn, and a silent widening is worse than the refusal.
    return context.workspace_id


def find_capability(
    capabilities: Iterable[AgentCapability], name: str, workspace_id: str | None
) -> AgentCapability | None:
    """The row at EXACTLY this scope. An org-wide row does not answer for a
    workspace-scoped lookup here, because a mutation resolves to one row and
    the union predicate the reads use would make that choice ambiguous."""
    return next(
        (
            item
            for item in capabilities
            if item.name == name and item.workspace_id == workspace_id
        ),
        None,
    )


def scope_view(workspace_id: str | None) -> dict[str, Any]:
    """The scope as it appears in a result body and an approval context."""
    return {
        "workspace_id": workspace_id,
        "scope": "organisation" if workspace_id is None else "workspace",
    }
