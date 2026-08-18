"""The noun/verb/binding registry + capability discovery (S7.2, US-KER-05).

Registering an adapter's verbs is pure data: ``register_adapter_verbs`` reads
the adapter's ``describe()`` and upserts nouns, verbs and bindings. No kernel
code changes when a new integration arrives (P1). Discovery returns only the
verbs a caller is scoped to see (P4, role-scoped).
"""

from __future__ import annotations

import logging
from functools import partial
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
from boltrig.store import Store

from .revertible import EffectLog

log = logging.getLogger("boltrig.kernel.registry")


class KernelRegistry:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def register_adapter_verbs(
        self,
        tenant_id: str,
        adapter: Adapter,
        *,
        effects: EffectLog | None = None,
    ) -> list[str]:
        """Register every verb an adapter provides. Returns the registered ids.

        DOES NOT OVERWRITE A BINDING IT DOES NOT OWN. Re-registration happens on
        every startup, and it used to upsert an ADAPTER binding unconditionally
        -- so a verb deliberately re-pointed at a reasoning agent by
        `bind_verb_to_agent` silently reverted the next time the process came
        up. Deactivation already declined to touch other people's bindings
        (VerbBinding.owned_by); this now declines on the way in too.

        Pass ``effects`` to receive an inverse for everything this call changes,
        built while what was displaced is still known. Absent, the behaviour is
        exactly as before minus the clobbering, so existing callers need no
        change.
        """
        registered: list[str] = []
        for spec in adapter.describe():
            await self._register_spec(tenant_id, adapter, spec, effects)
            registered.append(spec.verb_id)
        return registered

    async def _register_spec(
        self, tenant_id: str, adapter: Adapter, spec: Any, effects: EffectLog | None
    ) -> None:
        """Noun, verb and binding for ONE spec, plus the inverse of each.

        Extracted because the caller was a loop around exactly this, and at 86
        lines it broke the structural floor. Nothing here changed in the move.
        """
        if await self._store.get_noun(tenant_id, spec.noun_id) is None:
            await self._store.upsert_noun(Noun(id=spec.noun_id, tenant_id=tenant_id))
            if effects is not None:
                noun_id = spec.noun_id
                effects.record(
                    f"noun {noun_id}",
                    partial(self._store.delete_noun, tenant_id, noun_id),
                )
        previous_verb = await self._store.get_verb(tenant_id, spec.verb_id)
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
        if effects is not None:
            self._record_verb_inverse(effects, tenant_id, spec.verb_id, previous_verb)

        existing = await self._store.get_binding(tenant_id, spec.verb_id)
        if existing is not None and existing.target_type is TargetType.AGENT:
            # AN AGENT BINDING IS NEVER AN ADAPTER'S TO REPLACE.
            #
            # Two things produce one, and an adapter must not undo either: a
            # deliberate `bind_verb_to_agent` re-point, which used to revert
            # on the next restart because this loop upserted over it; and
            # `questions.py`'s `native:questions`, which the chokepoint
            # intercepts in-kernel, so overwriting it would quietly disable
            # the human-question pause.
            #
            # ADAPTER-over-ADAPTER is deliberately still allowed. Several
            # adapters publish the same verb on purpose -- jira and
            # memory-tickets both publish ticket.create, five audio adapters
            # publish voice.speak -- and last-registration-wins is how
            # manifest order picks the provider. Refusing that too booted
            # the stack onto whichever adapter happened to register first.
            log.info(
                "adapter %s left verb %s bound to agent:%s",
                adapter.id, spec.verb_id, existing.target_ref,
            )
            return

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
        if effects is not None:
            self._record_binding_inverse(effects, tenant_id, spec.verb_id, existing)

    def _record_verb_inverse(
        self, effects: EffectLog, tenant_id: str, verb_id: str, previous: Verb | None
    ) -> None:
        """Put back the verb that was there, or remove the one we added."""
        if previous is None:
            effects.record(
                f"verb {verb_id}",
                lambda: self._store.delete_verb(tenant_id, verb_id),
            )
        else:
            effects.record(
                f"verb {verb_id} (restore)",
                partial(self._store.upsert_verb, previous),
            )

    def _record_binding_inverse(
        self,
        effects: EffectLog,
        tenant_id: str,
        verb_id: str,
        previous: VerbBinding | None,
    ) -> None:
        """Put back the binding that was there, INCLUDING when there was none.

        The distinction is the reason the inverse is built here rather than
        written out somewhere else later: only this call site knows whether it
        created a binding or replaced one, and "delete it" is wrong in the
        second case.
        """
        if previous is None:
            effects.record(
                f"binding {verb_id}",
                lambda: self._store.delete_binding(tenant_id, verb_id),
            )
        else:
            effects.record(
                f"binding {verb_id} (restore)",
                partial(self._store.upsert_binding, previous),
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
