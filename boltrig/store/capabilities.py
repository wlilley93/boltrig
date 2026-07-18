"""Agent-capability persistence + scoped-declarative reconciliation.

The contract and both store implementations live here (mirroring
``budget_policy.py``) so ``base.py`` / ``memory.py`` / ``postgres.py`` compose a
mixin instead of carrying the bodies.

Scoped-declarative reconciliation ([2026] LEXBY LOG-2026-07-17): a capability
carries a ``source`` provenance and an ``is_active`` flag. ``list_capabilities``
returns only active rows (so ``select_capability`` can never route to a
deactivated capability); ``list_all_capabilities`` is the unfiltered admin/audit
read and is NEVER used on the routing path.
``deactivate_absent_manifest_capabilities`` is the reconcile seam a manifest
apply uses: it soft-deactivates the manifest-sourced rows a redeployed manifest
no longer declares, and it touches ONLY ``source='manifest'`` rows, so a governed
``source='control-plane'`` grant is never reconciled away.
"""

from __future__ import annotations

from typing import Protocol

from boltrig.models import AgentCapability


class CapabilityStoreContract(Protocol):
    async def upsert_capability(self, cap: AgentCapability) -> None: ...
    # Routing read: ACTIVE capabilities only (is_active = true).
    async def list_capabilities(self, tenant_id: str) -> list[AgentCapability]: ...
    # Admin/audit read: every capability, active or not. Never on the routing path.
    async def list_all_capabilities(self, tenant_id: str) -> list[AgentCapability]: ...
    # Reconcile seam (manifest apply only): soft-deactivate the manifest-sourced
    # capabilities NOT in ``declared_names``. Only ``source='manifest'`` rows are
    # ever touched; returns the names it deactivated (for audit).
    async def deactivate_absent_manifest_capabilities(
        self, tenant_id: str, declared_names: list[str]
    ) -> list[str]: ...


class CapabilityStoreMem:
    async def upsert_capability(self, cap):
        # A fresh or re-declared capability is always active: upsert RESETS the
        # flag (the memory mirror of the Postgres ON CONFLICT is_active=true).
        cap.is_active = True
        self._caps[(cap.tenant_id, cap.name)] = cap

    async def list_capabilities(self, tenant_id):
        return [
            c for (t, _), c in self._caps.items() if t == tenant_id and c.is_active
        ]

    async def list_all_capabilities(self, tenant_id):
        return [c for (t, _), c in self._caps.items() if t == tenant_id]

    async def deactivate_absent_manifest_capabilities(self, tenant_id, declared_names):
        declared = set(declared_names)
        deactivated: list[str] = []
        for (t, name), cap in self._caps.items():
            if (
                t == tenant_id
                and cap.source == "manifest"
                and cap.is_active
                and name not in declared
            ):
                cap.is_active = False
                deactivated.append(name)
        return sorted(deactivated)


class CapabilityStorePG:
    async def upsert_capability(self, c: AgentCapability):
        # ON CONFLICT sets source to the INCOMING value and RESETS is_active=true:
        # a manifest re-declaration reclaims ownership of a name and thereafter that
        # name lives under declarative reconciliation (the tie-break).
        await self._pool.execute(
            """INSERT INTO agent_capabilities (name, tenant_id, runtime, model_endpoint,
                                               supported_skills, max_depth, is_ephemeral,
                                               cost_tier, source, is_active)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,true)
               ON CONFLICT (tenant_id, name) DO UPDATE SET
                 runtime=EXCLUDED.runtime, model_endpoint=EXCLUDED.model_endpoint,
                 supported_skills=EXCLUDED.supported_skills, max_depth=EXCLUDED.max_depth,
                 is_ephemeral=EXCLUDED.is_ephemeral, cost_tier=EXCLUDED.cost_tier,
                 source=EXCLUDED.source, is_active=true, updated_at=now()""",
            c.name, c.tenant_id, c.runtime, c.model_endpoint, c.supported_skills,
            c.max_depth, c.is_ephemeral, c.cost_tier, c.source,
        )

    async def list_capabilities(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM agent_capabilities WHERE tenant_id=$1 AND is_active = true",
            tenant_id,
        )
        return [_capability(r) for r in rows]

    async def list_all_capabilities(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM agent_capabilities WHERE tenant_id=$1", tenant_id
        )
        return [_capability(r) for r in rows]

    async def deactivate_absent_manifest_capabilities(self, tenant_id, declared_names):
        # One atomic statement: no partial wipe can be observed, and only
        # source='manifest' active rows outside the declared set are touched.
        rows = await self._pool.fetch(
            """UPDATE agent_capabilities
               SET is_active = false, updated_at = now()
               WHERE tenant_id = $1 AND source = 'manifest' AND is_active = true
                 AND name <> ALL($2::text[])
               RETURNING name""",
            tenant_id, list(declared_names),
        )
        return [r["name"] for r in rows]


def _capability(r):
    if r is None:
        return None
    # Tolerate a pre-migration row (no source/is_active columns): default to a
    # governed, active grant, the fail-safe reading.
    return AgentCapability(
        name=r["name"], tenant_id=r["tenant_id"], runtime=r["runtime"],
        supported_skills=list(r["supported_skills"] or []), max_depth=r["max_depth"],
        is_ephemeral=r["is_ephemeral"], cost_tier=r["cost_tier"],
        model_endpoint=r["model_endpoint"],
        source=r["source"] if "source" in r else "control-plane",
        is_active=r["is_active"] if "is_active" in r else True,
    )
