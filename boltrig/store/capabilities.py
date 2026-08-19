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

Workspace scope (0083): a capability carries a ``workspace_id``, or NULL for an
ORG-WIDE profile every workspace sees. TWO DIFFERENT PREDICATES apply and
confusing them is the whole hazard:

* READS are the UNION - own workspace plus org-wide - via
  ``workspace_scope.append_workspace_scope_clause``. ``enforce_workspace=False``
  is the trusted unfiltered read an internal caller uses; it is the default so
  that no existing caller silently changes behaviour, and every routing caller
  opts in explicitly.
* WRITES, RETIREMENT and MANIFEST RECONCILIATION are EXACT - one scope, matched
  with ``IS NOT DISTINCT FROM``. The union predicate here would let an
  org-scoped manifest apply soft-deactivate every workspace's agents, which is
  exactly the silent failure this note exists to prevent.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
import json
from typing import TYPE_CHECKING, Any, Protocol

from boltrig.models import AgentCapability

from .model_endpoint_contract import lock_model_endpoint_reference_graph
from .workspace_scope import append_workspace_scope_clause, workspace_scope_visible


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
    # Routing read: ACTIVE capabilities only (is_active = true). With
    # ``enforce_workspace=True`` the answer is the caller's workspace UNION the
    # org-wide rows; the default is the trusted unfiltered read.
    async def list_capabilities(
        self,
        tenant_id: str,
        *,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> list[AgentCapability]: ...
    # ``list_all_capabilities`` is the admin/audit read, never the routing read.
    async def list_all_capabilities(
        self,
        tenant_id: str,
        *,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> list[AgentCapability]: ...
    # Reconcile seam (manifest apply only): soft-deactivate the manifest-sourced
    # capabilities NOT in ``declared_names``. Only ``source='manifest'`` rows are
    # ever touched; returns the names it deactivated (for audit). EXACT scope, not
    # the union: an org-scoped apply must not reach into a workspace's roster.
    async def deactivate_absent_manifest_capabilities(
        self,
        tenant_id: str,
        declared_names: list[str],
        *,
        workspace_id: str | None = None,
    ) -> list[str]: ...
    # Governed lifecycle seam: retain the row and all references while removing
    # it from every active routing read. EXACT scope.
    async def set_capability_active(
        self,
        tenant_id: str,
        name: str,
        active: bool,
        *,
        workspace_id: str | None = None,
    ) -> AgentCapability | None: ...


def capability_key(
    tenant_id: str, workspace_id: str | None, name: str
) -> tuple[str, str, str]:
    """The in-memory twin of ``agent_capabilities_scope_idx``.

    ``coalesce(workspace_id, '')`` in SQL and ``workspace_id or ""`` here are one
    rule; a mismatch between them is a parity bug that only appears once a
    workspace-scoped row exists, so both spellings live next to each other.
    """
    return (tenant_id, workspace_id or "", name)


class CapabilityStoreMem:
    async def upsert_capability(self, cap, *, preserve_status=False):
        with self._model_endpoint_lock:
            key = capability_key(cap.tenant_id, cap.workspace_id, cap.name)
            existing = self._caps.get(key)
            changed_references = (
                _capability_endpoint_ids(existing) ^ _capability_endpoint_ids(cap)
            )
            # Manifest re-declarations remain active by default. Governed authoring
            # opts into preserving a retired row so an ordinary edit cannot smuggle
            # it back into routing without the explicit restore verb.
            cap.is_active = (
                existing.is_active if preserve_status and existing is not None else True
            )
            self._caps[key] = cap
            self._bump_model_endpoint_revisions_locked(
                cap.tenant_id, changed_references
            )

    def _scoped_caps(self, tenant_id, workspace_id, enforce_workspace):
        return [
            c
            for key, c in self._caps.items()
            if key[0] == tenant_id
            and workspace_scope_visible(c, workspace_id, enforce_workspace)
        ]

    async def list_capabilities(
        self, tenant_id, *, workspace_id=None, enforce_workspace=False
    ):
        return [
            c
            for c in self._scoped_caps(tenant_id, workspace_id, enforce_workspace)
            if c.is_active
        ]

    async def list_all_capabilities(
        self, tenant_id, *, workspace_id=None, enforce_workspace=False
    ):
        return self._scoped_caps(tenant_id, workspace_id, enforce_workspace)

    async def deactivate_absent_manifest_capabilities(
        self, tenant_id, declared_names, *, workspace_id=None
    ):
        declared = set(declared_names)
        deactivated: list[str] = []
        for key, cap in self._caps.items():
            if (
                key[0] == tenant_id
                # EXACT scope, never `workspace_scope_visible`: an org-scoped
                # apply (workspace_id=None) must leave every roster alone.
                and cap.workspace_id == workspace_id
                and cap.source == "manifest"
                and cap.is_active
                and key[2] not in declared
            ):
                cap.is_active = False
                deactivated.append(key[2])
        return sorted(deactivated)

    async def set_capability_active(self, tenant_id, name, active, *, workspace_id=None):
        cap = self._caps.get(capability_key(tenant_id, workspace_id, name))
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
                   WHERE tenant_id=$1 AND name=$2
                     AND workspace_id IS NOT DISTINCT FROM $3""",
                c.tenant_id,
                c.name,
                c.workspace_id,
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
            # ON CONFLICT names the EXPRESSION index (0083), not a column list:
            # the arbiter has to be the same coalesce() the index is built on, or
            # Postgres cannot infer it and every insert raises rather than
            # updating.
            await conn.execute(
                """INSERT INTO agent_capabilities (name, tenant_id, runtime, model_endpoint,
                                                   vision_model_endpoint, model_routes, supported_skills, max_depth, is_ephemeral,
                                                   cost_tier, source, workspace_id, is_active)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,true)
                   ON CONFLICT (tenant_id, coalesce(workspace_id, ''), name) DO UPDATE SET
                     runtime=EXCLUDED.runtime, model_endpoint=EXCLUDED.model_endpoint,
                     vision_model_endpoint=EXCLUDED.vision_model_endpoint,
                     model_routes=EXCLUDED.model_routes,
                     supported_skills=EXCLUDED.supported_skills, max_depth=EXCLUDED.max_depth,
                     is_ephemeral=EXCLUDED.is_ephemeral, cost_tier=EXCLUDED.cost_tier,
                     source=EXCLUDED.source,
                     is_active=CASE WHEN $13 THEN agent_capabilities.is_active ELSE true END,
                     updated_at=now()""",
                c.name, c.tenant_id, c.runtime, c.model_endpoint, c.vision_model_endpoint,
                c.model_routes, c.supported_skills, c.max_depth,
                c.is_ephemeral, c.cost_tier, c.source, c.workspace_id,
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

    async def _scoped_rows(self, tenant_id, workspace_id, enforce_workspace, extra):
        clauses = ["tenant_id=$1", *extra]
        args: list[Any] = [tenant_id]
        append_workspace_scope_clause(clauses, args, workspace_id, enforce_workspace)
        rows = await self._pool.fetch(
            f"SELECT * FROM agent_capabilities WHERE {' AND '.join(clauses)}", *args
        )
        return [_capability(r) for r in rows]

    async def list_capabilities(
        self, tenant_id, *, workspace_id=None, enforce_workspace=False
    ):
        return await self._scoped_rows(
            tenant_id, workspace_id, enforce_workspace, ["is_active = true"]
        )

    async def list_all_capabilities(
        self, tenant_id, *, workspace_id=None, enforce_workspace=False
    ):
        return await self._scoped_rows(tenant_id, workspace_id, enforce_workspace, [])

    async def deactivate_absent_manifest_capabilities(
        self, tenant_id, declared_names, *, workspace_id=None
    ):
        # One atomic statement: no partial wipe can be observed, and only
        # source='manifest' active rows outside the declared set are touched.
        #
        # IS NOT DISTINCT FROM, not the union predicate the reads use. A manifest
        # is an org-scoped artefact, so without this an apply would soft-deactivate
        # every workspace's manifest agents the moment rosters became scoped -
        # silent, because a deactivated row still exists and only stops being
        # routable.
        rows = await self._pool.fetch(
            """UPDATE agent_capabilities
               SET is_active = false, updated_at = now()
               WHERE tenant_id = $1 AND source = 'manifest' AND is_active = true
                 AND workspace_id IS NOT DISTINCT FROM $3
                 AND name <> ALL($2::text[])
               RETURNING name""",
            tenant_id, list(declared_names), workspace_id,
        )
        return [r["name"] for r in rows]

    async def set_capability_active(self, tenant_id, name, active, *, workspace_id=None):
        row = await self._pool.fetchrow(
            """UPDATE agent_capabilities SET is_active=$3, updated_at=now()
               WHERE tenant_id=$1 AND name=$2
                 AND workspace_id IS NOT DISTINCT FROM $4
               RETURNING *""",
            tenant_id, name, bool(active), workspace_id,
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
        workspace_id=r["workspace_id"] if "workspace_id" in r else None,
    )
