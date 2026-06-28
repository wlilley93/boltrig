"""The noun/verb/binding registry + capability discovery (S7.2, US-KER-05).

Registering an adapter's verbs is pure data: ``register_adapter_verbs`` reads
the adapter's ``describe()`` and upserts nouns, verbs and bindings. No kernel
code changes when a new integration arrives (P1). Discovery returns only the
verbs a caller is scoped to see (P4, role-scoped).
"""

from __future__ import annotations

from typing import Any

from nankle.adapters.base import Adapter
from nankle.models import (
    Consequence,
    InvocationContext,
    Noun,
    RateLimit,
    TargetType,
    TenantPermissions,
    Verb,
    VerbBinding,
)
from nankle.store import Store


class KernelRegistry:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def register_adapter_verbs(self, tenant_id: str, adapter: Adapter) -> list[str]:
        """Register every verb an adapter provides. Returns the registered ids."""
        registered: list[str] = []
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
        return registered

    async def bind_verb_to_agent(
        self, tenant_id: str, verb_id: str, agent_capability: str
    ) -> None:
        """Re-point a verb at a reasoning agent instead of an adapter (US-KER-02).
        The caller's interface is unchanged (P4)."""
        await self._store.upsert_binding(
            VerbBinding(
                verb_id=verb_id,
                tenant_id=tenant_id,
                target_type=TargetType.AGENT,
                target_ref=agent_capability,
            )
        )

    async def discover(
        self,
        tenant_id: str,
        perms: TenantPermissions,
        context: InvocationContext | None = None,
        noun_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the noun/verb map the caller is permitted to see (role-scoped)."""
        verbs = await self._store.list_verbs(tenant_id, noun_id)
        visible = [v for v in verbs if perms.grants.permits(v.id)]
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
                    "binding": (
                        {"target_type": binding.target_type.value, "target_ref": binding.target_ref}
                        if binding
                        else None
                    ),
                }
            )
        return {"verbs": out}
