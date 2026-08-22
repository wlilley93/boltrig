"""Scoped-declarative capability reconciliation for ``apply_manifest``.

Binding court order [2026] LEXBY LOG-2026-07-17-120214 (SUBMISSION-2026-07-17-
115737): the fleet manifest is DECLARATIVE over the capabilities it authored and
ADDITIVE over all others. A capability the manifest authored
(``source='manifest'``) that a redeployed manifest no longer declares is
soft-deactivated so it can no longer be selected (stale attack surface removed);
a governed grant (``source='control-plane'``, minted by
``control.capability.upsert``) is NEVER touched by a manifest apply.

The guard evaluation (:func:`plan_capability_reconciliation`) runs BEFORE any
store write, so a tripped mass-deactivation guard aborts the whole apply with
nothing committed (fail-closed). The actual soft-deactivation
(:func:`reconcile_capabilities`) runs AFTER the upsert loop through a single
atomic store statement, so no partial wipe can be observed.

A manifest carries a tenant and no workspace, so both the plan and the
reconciliation are pinned to the ORG-WIDE scope (``workspace_id=None``,
matched exactly). Since 0083 gave capabilities a workspace, an unscoped
reconcile would soft-deactivate every workspace's manifest agents on the first
apply after a workspace authored one - invisibly, because a deactivated row
still exists and merely stops being routable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from boltrig.models import ActionType, AgentCapability, AuditEvent, utcnow

if TYPE_CHECKING:  # imported for typing only; avoids a manifest <-> reconcile cycle
    from .manifest import EphemeralRuntime, FleetManifest, NamedAgentConfig

MANIFEST_SOURCE = "manifest"
# The mass-deactivation floor: an apply may drop at most this many manifest-sourced
# capabilities (or half the active manifest-sourced set, whichever is larger)
# without an explicit confirm.
_MIN_ABSOLUTE_DROP = 3


class BulkCapabilityDeactivationError(RuntimeError):
    """A manifest apply would soft-deactivate an unsafe number of capabilities.

    Raised BEFORE any store write so the whole apply aborts with nothing
    committed. Override with ``reconcile.allow_bulk_deactivate: true`` in the
    manifest or ``confirm_bulk_deactivate=True`` on :func:`apply_manifest`.
    """


def _capability_from_named_agent(
    agent: NamedAgentConfig, tenant_id: str
) -> AgentCapability:
    return AgentCapability(
        name=agent.name, tenant_id=tenant_id, runtime=agent.runtime,
        supported_skills=list(agent.supported_skills), max_depth=agent.max_depth,
        is_ephemeral=False, cost_tier=agent.cost_tier,
        model_endpoint=agent.model_endpoint, source=MANIFEST_SOURCE,
    )


def _capability_from_ephemeral(rt: EphemeralRuntime, tenant_id: str) -> AgentCapability:
    return AgentCapability(
        name=rt.name, tenant_id=tenant_id, runtime=rt.runtime,
        supported_skills=list(rt.supported_skills), max_depth=rt.max_depth,
        is_ephemeral=True, cost_tier=rt.cost_tier,
        model_endpoint=rt.model_endpoint, source=MANIFEST_SOURCE,
    )


def declared_capabilities(manifest: FleetManifest) -> list[AgentCapability]:
    """Every ephemeral runtime and durable named peer authored by the manifest."""
    from .manifest import resolved_named_agents

    tenant = manifest.tenant_id
    caps = [_capability_from_ephemeral(rt, tenant) for rt in manifest.ephemeral_runtimes]
    caps.extend(
        _capability_from_named_agent(agent, tenant)
        for agent in resolved_named_agents(manifest).members
    )
    return caps


@dataclass(frozen=True)
class ReconciliationPlan:
    """The pre-computed declarative plan: the names the manifest declares and the
    manifest-sourced names it dropped (to soft-deactivate)."""

    declared_names: frozenset[str]
    absent_names: tuple[str, ...]


def _allow_bulk(manifest: FleetManifest, confirm_bulk_deactivate: bool) -> bool:
    if confirm_bulk_deactivate:
        return True
    return bool(manifest.section("reconcile").get("allow_bulk_deactivate", False))


async def plan_capability_reconciliation(
    store: Any, manifest: FleetManifest, *, confirm_bulk_deactivate: bool = False
) -> ReconciliationPlan:
    """Compute the plan and enforce the mass-deactivation guard BEFORE any write.

    Only ``source='manifest'`` rows are ever candidates; ``source='control-plane'``
    rows are never inspected. ``D`` = the count of active manifest-sourced names the
    manifest dropped; ``A`` = the count of active manifest-sourced rows before this
    apply. Raises :class:`BulkCapabilityDeactivationError` (nothing committed) when
    the manifest declares zero capabilities, OR when ``D > max(3, floor(A/2))``,
    unless an explicit confirm overrides. The empty-manifest clause is
    unconditional (it does not depend on the counts).
    """
    declared_names = frozenset(c.name for c in declared_capabilities(manifest))
    # ORG-WIDE ONLY. A fleet manifest carries a tenant and no workspace, so it
    # authors org-wide rows and reconciles org-wide rows. Reading the unfiltered
    # set instead would count every workspace's manifest agents into A and list
    # their names in `absent`, so the mass-deactivation guard would fire on
    # arithmetic about rows this apply cannot touch, and the plan would promise
    # drops that never happen.
    active = await store.list_capabilities(
        manifest.tenant_id, workspace_id=None, enforce_workspace=True
    )
    active_manifest = [c for c in active if c.source == MANIFEST_SOURCE]
    absent = tuple(sorted(c.name for c in active_manifest if c.name not in declared_names))
    a_before, dropped = len(active_manifest), len(absent)
    if not _allow_bulk(manifest, confirm_bulk_deactivate):
        empty = len(declared_names) == 0
        over_threshold = dropped > max(_MIN_ABSOLUTE_DROP, a_before // 2)
        if empty or over_threshold:
            reason = "declares no capabilities" if empty else (
                f"would drop {dropped} of {a_before} manifest-sourced capabilities"
            )
            raise BulkCapabilityDeactivationError(
                f"manifest apply for tenant '{manifest.tenant_id}' {reason}; set "
                "reconcile.allow_bulk_deactivate or pass confirm_bulk_deactivate=True"
            )
    return ReconciliationPlan(declared_names=declared_names, absent_names=absent)


async def reconcile_capabilities(
    kernel: Any, manifest: FleetManifest, plan: ReconciliationPlan
) -> list[str]:
    """Soft-deactivate the manifest-sourced capabilities the manifest dropped and
    write one audit record per deactivation (who: manifest apply; what: the
    capability name). Touches ONLY ``source='manifest'`` rows (the store fences
    that); returns the deactivated names."""
    if not plan.absent_names:
        return []
    deactivated = await kernel.store.deactivate_absent_manifest_capabilities(
        manifest.tenant_id, list(plan.declared_names), workspace_id=None
    )
    audit = getattr(kernel, "audit", None)
    for name in deactivated:
        if audit is None:
            break
        await audit.write(
            AuditEvent(
                tenant_id=manifest.tenant_id, ts=utcnow(), actor="manifest-apply",
                action_type=ActionType.TOOL_CALL, status="ok",
                noun="capability", verb="control.capability.deactivate",
                resource="agent_capability", resource_id=name,
                detail={"reason": "absent from redeployed manifest", "source": MANIFEST_SOURCE},
            )
        )
    return deactivated
