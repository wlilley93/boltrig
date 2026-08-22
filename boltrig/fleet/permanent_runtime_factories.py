"""Compatibility constructors for permanent and flat named runtimes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .permanent_runtime import PermanentAgentRuntime

if TYPE_CHECKING:
    from boltrig.config.manifest import FleetManifest, HierarchyTier, NamedAgentConfig

    from .spawn import Spawner


def head(
    spawner: Spawner,
    manifest: FleetManifest,
    tier: HierarchyTier,
    department: str,
) -> PermanentAgentRuntime:
    """Construct one lazy legacy department-head profile."""
    return PermanentAgentRuntime.from_manifest(
        spawner,
        tier,
        manifest.tenant_id,
        role="tier2",
        department=department,
    )


def chief(
    spawner: Spawner,
    manifest: FleetManifest | None,
) -> PermanentAgentRuntime | None:
    """Construct the lazy legacy Chief profile when one is declared."""
    tier = manifest.hierarchy.tier1 if manifest is not None else None
    if tier is None:
        return None
    assert manifest is not None
    return PermanentAgentRuntime.from_manifest(
        spawner,
        tier,
        manifest.tenant_id,
        role="tier1",
        department=None,
    )


def named(
    spawner: Spawner,
    manifest: FleetManifest,
    agent: NamedAgentConfig,
) -> PermanentAgentRuntime:
    """Construct one lazy runtime for a flat durable named peer."""
    return PermanentAgentRuntime.from_named_agent(spawner, agent, manifest.tenant_id)
