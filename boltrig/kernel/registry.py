"""The noun/verb/binding registry + capability discovery (S7.2, US-KER-05).

Registering an adapter's verbs is pure data: ``register_adapter_verbs`` reads
the adapter's ``describe()`` and upserts nouns, verbs and bindings. No kernel
code changes when a new integration arrives (P1). Discovery returns only the
verbs a caller is scoped to see (P4, role-scoped).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from boltrig.adapters.base import Adapter
from boltrig.models import (
    Consequence,
    derive_familiar_genotype,
    IdempotencyMode,
    InvocationContext,
    Noun,
    RateLimit,
    TargetType,
    TenantPermissions,
    Verb,
    VerbBinding,
)
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    SourceOperation,
)
from boltrig.store import Store


def _schema_digest(spec: Any) -> str:
    """A stable fingerprint of the operation's contract.

    Recorded on both the source operation and the binding that claims it, so a
    provider changing a schema under a published capability is detectable rather
    than silent - the failure mode the doctrine's catalogue revisions exist for.
    """
    payload = json.dumps(
        [spec.input_schema, spec.output_schema], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KernelRegistry:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def register_adapter_verbs(self, tenant_id: str, adapter: Adapter) -> list[str]:
        """Register every verb an adapter provides. Returns the registered ids.

        A spec declaring ``implements`` ALSO records the doctrine's three routing
        records - a provider connection, the source operation, and the binding
        that claims a canonical capability (SPEC §5 level 1). Everything else is
        unchanged, so an adapter that declares nothing behaves exactly as before.
        """
        registered: list[str] = []
        declared = [spec for spec in adapter.describe() if spec.implements]
        connection = (
            await self._capability_connection(tenant_id, adapter) if declared else None
        )
        for spec in adapter.describe():
            if await self._store.get_noun(tenant_id, spec.noun_id) is None:
                await self._store.upsert_noun(Noun(id=spec.noun_id, tenant_id=tenant_id))
            await self._store.upsert_verb(
                Verb(
                    id=spec.verb_id,
                    tenant_id=tenant_id,
                    noun_id=spec.noun_id,
                    input_schema=spec.input_schema,
                    output_schema=spec.output_schema,
                    description=spec.description,
                    consequence=Consequence(spec.consequence),
                    degraded_mode=spec.degraded_mode,
                    idempotency_mode=IdempotencyMode(spec.idempotency_mode),
                )
            )
            rl = spec.rate_limit
            await self._store.upsert_binding(
                VerbBinding(
                    verb_id=spec.verb_id,
                    tenant_id=tenant_id,
                    target_type=TargetType.ADAPTER,
                    target_ref=adapter.id,
                    rate_limit=RateLimit(**rl) if rl else None,
                )
            )
            registered.append(spec.verb_id)
        for spec in declared:
            assert connection is not None
            await self._declare_capability(tenant_id, connection, spec)
        return registered

    async def _capability_connection(
        self, tenant_id: str, adapter: Adapter
    ) -> ProviderConnection:
        """The routing identity for this adapter's operations.

        Its LABEL is the authoritative one from the catalogue connection when the
        tenant has configured one, because that is the name a confirmation prompt
        has to be able to say out loud ("Archive Alice Morgan in HubSpot - UK
        Sales?"). Absent a catalogue row the adapter id is the honest fallback.
        """
        label = adapter.id
        integration_connection_id = None
        for row in await self._store.list_integration_connections(tenant_id):
            if row.adapter_id == adapter.id and row.health != "revoked":
                label, integration_connection_id = row.label, row.id
                break
        connection = ProviderConnection(
            id=f"pconn:{adapter.id}",
            tenant_id=tenant_id,
            label=label,
            provider=adapter.id,
            source_type=getattr(adapter, "source_type", "native"),
            adapter_id=adapter.id,
            integration_connection_id=integration_connection_id,
            # An adapter that SHIPS INSIDE THE IMAGE is first-party; anything
            # generated, consumed or hand-authored is merely reviewed, and its
            # declared claims stay proposed until someone approves them.
            trust_level=(
                "first_party"
                if getattr(adapter, "source", "builtin") == "builtin"
                else "reviewed"
            ),
        )
        await self._store.upsert_provider_connection(connection)
        return connection

    async def _declare_capability(
        self, tenant_id: str, connection: ProviderConnection, spec: Any
    ) -> None:
        """Record one declared implementation claim.

        A FIRST-PARTY adapter's claim binds approved: it ships inside the image
        and its registration is already the governed act. Anything generated,
        consumed or hand-authored lands ``proposed`` - a declaration is evidence,
        never the authority to publish itself (SPEC §5, approval policy). An
        unapproved binding is not eligible for any route.
        """
        digest = _schema_digest(spec)
        await self._store.upsert_source_operation(
            SourceOperation(
                id=spec.verb_id,
                tenant_id=tenant_id,
                provider=connection.provider,
                source_type=connection.source_type,
                connection_id=connection.id,
                title=spec.verb_id,
                description=spec.description,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                schema_digest=digest,
                consequence_hint=spec.consequence,
            )
        )
        first_party = connection.trust_level == "first_party"
        await self._store.upsert_capability_binding(
            CapabilityBinding(
                binding_id=f"cb:{connection.id}:{spec.verb_id}",
                tenant_id=tenant_id,
                capability_id=spec.implements,
                capability_version=spec.capability_version,
                source_operation_id=spec.verb_id,
                connection_id=connection.id,
                status="approved" if first_party else "proposed",
                trust_level=connection.trust_level,
                source_schema_digest=digest,
                created_from="declared",
            )
        )

    async def bind_verb_to_agent(self, tenant_id: str, verb_id: str, agent_capability: str) -> None:
        """Re-point a verb at a reasoning agent instead of an adapter (US-KER-02).
        The caller's interface is unchanged (P4)."""
        if await self._store.get_verb(tenant_id, verb_id) is None:
            raise LookupError("verb or noun is missing or archived")
        await self._store.upsert_binding(
            VerbBinding(
                verb_id=verb_id,
                tenant_id=tenant_id,
                target_type=TargetType.AGENT,
                target_ref=agent_capability,
            )
        )

    async def _noun_views(self, tenant_id: str, verbs: list[Verb]) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        for noun_id in sorted({verb.noun_id for verb in verbs}):
            noun = await self._store.get_noun(tenant_id, noun_id)
            if noun is not None:
                views.append(
                    {
                        "id": noun.id,
                        "description": noun.description,
                        "schema": noun.schema,
                    }
                )
        return views

    async def _workflow_views(
        self, tenant_id: str, workspace_id: str | None
    ) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        for workflow in await self._store.list_workflows(tenant_id):
            if workflow.workspace_id is not None and workflow.workspace_id != workspace_id:
                continue
            definition = workflow.definition if isinstance(workflow.definition, dict) else {}
            input_schema = definition.get("input_schema", {})
            views.append(
                {
                    "id": workflow.id,
                    "version": workflow.version,
                    "source": workflow.source.value,
                    "workspace_id": workflow.workspace_id,
                    "input_schema": input_schema if isinstance(input_schema, dict) else {},
                }
            )
        return sorted(views, key=lambda workflow: workflow["id"])

    async def _agent_profile_views(self, tenant_id: str) -> list[dict[str, Any]]:
        views = [
            {
                "name": capability.name,
                "runtime": capability.runtime,
                "supported_skills": capability.supported_skills,
                "max_depth": capability.max_depth,
                "is_ephemeral": capability.is_ephemeral,
                "cost_tier": capability.cost_tier,
                "model_endpoint": capability.model_endpoint,
                "vision_model_endpoint": capability.vision_model_endpoint,
                "model_routes": capability.model_routes,
                "familiar_genotype": derive_familiar_genotype(
                    capability.name
                ).as_view(),
            }
            for capability in await self._store.list_capabilities(tenant_id)
        ]
        return sorted(views, key=lambda profile: profile["name"])

    async def discover(
        self,
        tenant_id: str,
        perms: TenantPermissions,
        context: InvocationContext | None = None,
        noun_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the caller-visible discovery catalogue.

        Verb and noun visibility is the intersection of the tenant ceiling and
        the caller's grants.  Workflows additionally honour the caller's active
        workspace, while agent capability profiles are tenant-scoped library
        records.  The verb payload is deliberately kept backward-compatible.
        """
        verbs = await self._store.list_verbs(tenant_id, noun_id)
        # A verb is visible iff the tenant ceiling permits it AND the caller's own
        # (role-scoped) grants permit it - the US-IAM-02 / US-KER-05 intersection.
        # With no caller context, fall back to the ceiling (internal callers).
        caller = context.grants if context is not None else None
        visible = [
            v
            for v in verbs
            if perms.grants.permits(v.id) and (caller is None or caller.permits(v.id))
        ]
        out: list[dict[str, Any]] = []
        for v in visible:
            binding = await self._store.get_binding(tenant_id, v.id)
            out.append(
                {
                    "id": v.id,
                    "noun": v.noun_id,
                    "input_schema": v.input_schema,
                    "output_schema": v.output_schema,
                    "consequence": v.consequence.value,
                    "idempotency_mode": v.idempotency_mode.value,
                    "binding": (
                        {"target_type": binding.target_type.value, "target_ref": binding.target_ref}
                        if binding
                        else None
                    ),
                }
            )

        workspace_id = context.workspace_id if context is not None else None
        return {
            "nouns": await self._noun_views(tenant_id, visible),
            "verbs": out,
            "workflows": await self._workflow_views(tenant_id, workspace_id),
            "agent_capabilities": await self._agent_profile_views(tenant_id),
        }
