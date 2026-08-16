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
Governed profile edits use ``preserve_status=True`` so editing a retired row
cannot reactivate it; only the explicit lifecycle seam does that.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
import json
from typing import TYPE_CHECKING, Any, Protocol

from boltrig.models import AgentCapability

from .model_endpoint_contract import lock_model_endpoint_reference_graph


def _capability_endpoint_ids(capability: AgentCapability | None) -> set[str]:
    if capability is None:
        return set()
    return {
        endpoint_id
        for endpoint_id in (
            capability.model_endpoint,
            capability.vision_model_endpoint,
            *capability.model_routes.values(),
        )
        if endpoint_id is not None
    }


def _model_routes_value(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, dict) else {}


class CapabilityStoreContract(Protocol):
    async def upsert_capability(
        self, cap: AgentCapability, *, preserve_status: bool = False
    ) -> None: ...
    # Routing read: ACTIVE capabilities only (is_active = true).
    async def list_capabilities(self, tenant_id: str) -> list[AgentCapability]: ...
    # ``list_all_capabilities`` is the admin/audit read, never the routing read.
    async def list_all_capabilities(self, tenant_id: str) -> list[AgentCapability]: ...
    # Reconcile seam (manifest apply only): soft-deactivate the manifest-sourced
    # capabilities NOT in ``declared_names``. Only ``source='manifest'`` rows are
    # ever touched; returns the names it deactivated (for audit).
    async def deactivate_absent_manifest_capabilities(
        self, tenant_id: str, declared_names: list[str]
    ) -> list[str]: ...
    # Governed lifecycle seam: retain the row and all references while removing
    # it from every active routing read.
    async def set_capability_active(
        self, tenant_id: str, name: str, active: bool
    ) -> AgentCapability | None: ...


class CapabilityStoreMem:
    async def upsert_capability(self, cap, *, preserve_status=False):
        with self._model_endpoint_lock:
            existing = self._caps.get((cap.tenant_id, cap.name))
            changed_references = (
                _capability_endpoint_ids(existing) ^ _capability_endpoint_ids(cap)
            )
            # Manifest re-declarations remain active by default. Governed authoring
            # opts into preserving a retired row so an ordinary edit cannot smuggle
            # it back into routing without the explicit restore verb.
            cap.is_active = (
                existing.is_active if preserve_status and existing is not None else True
            )
            self._caps[(cap.tenant_id, cap.name)] = cap
            self._bump_model_endpoint_revisions_locked(
                cap.tenant_id, changed_references
            )

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

    async def set_capability_active(self, tenant_id, name, active):
        cap = self._caps.get((tenant_id, name))
        if cap is None:
            return None
        cap.is_active = bool(active)
        return cap


class CapabilityStorePG:
    if TYPE_CHECKING:
        _pool: Any

        def with_tenant(
            self, tenant_id: str
        ) -> AbstractAsyncContextManager[Any]: ...

    async def upsert_capability(self, c: AgentCapability, *, preserve_status=False):
        # By default ON CONFLICT sets source to the incoming value and resets
        # is_active=true: a manifest re-declaration reclaims ownership of a name.
        # Governed author edits opt into preserving the prior lifecycle state.
        async with self.with_tenant(c.tenant_id) as conn:
            await lock_model_endpoint_reference_graph(conn, c.tenant_id)
            row = await conn.fetchrow(
                """SELECT model_endpoint, vision_model_endpoint, model_routes
                   FROM agent_capabilities
                   WHERE tenant_id=$1 AND name=$2""",
                c.tenant_id,
                c.name,
            )
            existing_ids = set()
            if row is not None:
                existing_ids = {
                    endpoint_id
                    for endpoint_id in (
                        row["model_endpoint"],
                        row["vision_model_endpoint"],
                        *(
                            _model_routes_value(row["model_routes"]).values()
                            if "model_routes" in row
                            else ()
                        ),
                    )
                    if endpoint_id is not None
                }
            await conn.execute(
                """INSERT INTO agent_capabilities (name, tenant_id, runtime, model_endpoint,
                                                   vision_model_endpoint, model_routes, supported_skills, max_depth, is_ephemeral,
                                                   cost_tier, source, is_active)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,true)
                   ON CONFLICT (tenant_id, name) DO UPDATE SET
                     runtime=EXCLUDED.runtime, model_endpoint=EXCLUDED.model_endpoint,
                     vision_model_endpoint=EXCLUDED.vision_model_endpoint,
                     model_routes=EXCLUDED.model_routes,
                     supported_skills=EXCLUDED.supported_skills, max_depth=EXCLUDED.max_depth,
                     is_ephemeral=EXCLUDED.is_ephemeral, cost_tier=EXCLUDED.cost_tier,
                     source=EXCLUDED.source,
                     is_active=CASE WHEN $12 THEN agent_capabilities.is_active ELSE true END,
                     updated_at=now()""",
                c.name, c.tenant_id, c.runtime, c.model_endpoint, c.vision_model_endpoint,
                c.model_routes, c.supported_skills, c.max_depth,
                c.is_ephemeral, c.cost_tier, c.source,
                preserve_status,
            )
            changed_references = existing_ids ^ _capability_endpoint_ids(c)
            if changed_references:
                await conn.execute(
                    """UPDATE model_endpoints
                       SET revision=revision+1, updated_at=now()
                       WHERE tenant_id=$1 AND id=ANY($2::text[])""",
                    c.tenant_id,
                    sorted(changed_references),
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

    async def set_capability_active(self, tenant_id, name, active):
        row = await self._pool.fetchrow(
            """UPDATE agent_capabilities SET is_active=$3, updated_at=now()
               WHERE tenant_id=$1 AND name=$2 RETURNING *""",
            tenant_id, name, bool(active),
        )
        return _capability(row)


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
        vision_model_endpoint=(
            r["vision_model_endpoint"] if "vision_model_endpoint" in r else None
        ),
        model_routes=(
            _model_routes_value(r["model_routes"]) if "model_routes" in r else {}
        ),
        source=r["source"] if "source" in r else "control-plane",
        is_active=r["is_active"] if "is_active" in r else True,
    )
