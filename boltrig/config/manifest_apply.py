"""Store projection for a fully typed fleet manifest."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from boltrig.models import Budget, ConfigRevision, NamedAgent, TenantPermissions

from .manifest_reconcile import (
    declared_capabilities,
    plan_capability_reconciliation,
    reconcile_capabilities,
)


async def _seed_call(store: Any, method: str, *args: Any) -> None:
    fn = getattr(store, method, None)
    if fn is None:
        raise RuntimeError(
            f"store {type(store).__name__} lacks seed helper {method!r}; "
            "apply_manifest requires a seedable store "
            "(e.g. InMemoryStore, PostgresStore)"
        )
    result = fn(*args)
    if inspect.isawaitable(result):
        await result


def _budget_from_tier(
    tier: Any, tenant_id: str, *, scope_type: str, scope_id: str
) -> Budget:
    budget = tier.budget
    assert budget is not None
    return Budget(
        id=scope_id,
        tenant_id=tenant_id,
        scope_type=scope_type,
        token_limit=budget.token_limit,
        cost_limit_micros=budget.cost_limit_micros,
        hard_stop=budget.hard_stop,
        window=budget.window,
    )


async def _seed_tier_budgets(store: Any, manifest: Any, tenant: str) -> None:
    """Reconcile flat-agent budget policy without resetting accumulated usage."""
    from .manifest import resolved_named_agents

    roster = resolved_named_agents(manifest)
    for agent in roster.members:
        if not agent.budget:
            continue
        tenant_budget = agent.address == roster.default and agent.scope_id is None
        await _seed_call(
            store,
            "upsert_budget_policy",
            _budget_from_tier(
                agent,
                tenant,
                scope_type="tenant" if tenant_budget else "department",
                scope_id=tenant if tenant_budget else (agent.scope_id or agent.address),
            ),
        )


async def _seed_named_agents(store: Any, manifest: Any) -> None:
    """Project the manifest roster into the durable address registry."""
    from .manifest import resolved_named_agents

    roster = resolved_named_agents(manifest)
    for agent in roster.members:
        await store.upsert_named_agent(
            NamedAgent(
                tenant_id=manifest.tenant_id,
                address=agent.address,
                name=agent.name,
                runtime=agent.runtime,
                model_endpoint=agent.model_endpoint,
                supported_skills=list(agent.supported_skills),
                max_depth=agent.max_depth,
                cost_tier=agent.cost_tier,
                purpose=agent.purpose,
                brief=agent.brief,
                scope_id=agent.scope_id,
                default_for_intake=agent.address == roster.default,
            )
        )
    await store.deactivate_absent_named_agents(
        manifest.tenant_id, [agent.address for agent in roster.members]
    )


async def _seed_credentials(
    kernel: Any, store: Any, manifest: Any, tenant: str
) -> None:
    for adapter in manifest.adapters:
        if adapter.credential is not None:
            credential = adapter.credential
            await _seed_call(
                store,
                "set_credential_ref",
                tenant,
                credential.id,
                credential.as_ref(),
            )
            kernel.credentials.bind_adapter_credential(
                tenant, adapter.id, credential.id
            )


async def _register_manifest_adapters(
    kernel: Any, manifest: Any, tenant: str
) -> None:
    from .manifest import _BUILTIN_MODULES

    for adapter in manifest.adapters:
        module_path = _BUILTIN_MODULES.get(adapter.id) or adapter.module_ref
        if not module_path:
            continue
        mod_name, _, factory = module_path.partition(":")
        module = importlib.import_module(mod_name)
        build = getattr(module, factory or "build")
        await kernel.register_adapter(tenant, build())


async def _permanent_state(store: Any, manifest: Any) -> tuple[Any, Any]:
    # The legacy permanent-fleet desired-state document models one chief plus
    # departments. A flat roster must never be rewritten through that shape or
    # re-acquire tiers on restart. Named-agent policy is projected directly.
    if manifest.named_agents.members:
        return manifest, None
    from .permanent_fleet import (
        effective_manifest_from_desired,
        hierarchy_from_manifest,
        latest_permanent_fleet_revision,
    )

    revision = await latest_permanent_fleet_revision(
        store, manifest.tenant_id
    )
    initial_hierarchy = (
        hierarchy_from_manifest(manifest) if revision is None else None
    )
    if revision is not None:
        manifest = await effective_manifest_from_desired(store, manifest)
    return manifest, initial_hierarchy


async def _seed_projection(
    kernel: Any,
    manifest: Any,
    *,
    load_builtin_adapters: bool,
) -> None:
    tenant = manifest.tenant_id
    store = kernel.store
    for endpoint in manifest.models.endpoints:
        await store.upsert_model_endpoint(endpoint)
    cost = getattr(kernel, "cost", None)
    if cost is not None and manifest.models.prices:
        cost.set_prices(manifest.models.prices)
    for capability in declared_capabilities(manifest):
        await store.upsert_capability(capability)
    await _seed_named_agents(store, manifest)
    await _seed_tier_budgets(store, manifest, tenant)
    await _seed_call(
        store,
        "set_tenant_permissions",
        TenantPermissions(tenant, manifest.tenant_grants()),
    )
    from boltrig.kernel.questions import register_questions_verb

    await register_questions_verb(store, tenant)
    await _seed_credentials(kernel, store, manifest, tenant)
    if load_builtin_adapters:
        await _register_manifest_adapters(kernel, manifest, tenant)


async def apply_manifest(
    kernel: Any,
    manifest: Any,
    *,
    load_builtin_adapters: bool = True,
    confirm_bulk_deactivate: bool = False,
) -> None:
    """Project one manifest after enforcing the reconciliation guard."""
    from .manifest import export_runtime_environment
    from .permanent_fleet import permanent_fleet_generation

    export_runtime_environment(manifest)
    # The manifest network posture becomes the PROCESS-WIDE egress default
    # (SEC-52) BEFORE any adapter is built: the module-ref factories below are
    # called as plain ``build()`` and have no construction seam to receive it,
    # so without this an operator's air-gap / allow-list policy is silently
    # void for them. Explicit constructor configs always supersede it. Only a
    # typed NetworkConfig installs (a composition-root stub stays inert).
    from boltrig.adapters.egress import set_default_network_config
    from .manifest import NetworkConfig

    network = getattr(manifest, "network", None)
    if isinstance(network, NetworkConfig):
        set_default_network_config(network.as_egress_config())
    store = kernel.store
    manifest, initial_hierarchy = await _permanent_state(store, manifest)
    plan = await plan_capability_reconciliation(
        store,
        manifest,
        confirm_bulk_deactivate=confirm_bulk_deactivate,
    )
    await _seed_projection(
        kernel,
        manifest,
        load_builtin_adapters=load_builtin_adapters,
    )
    await reconcile_capabilities(kernel, manifest, plan)
    if initial_hierarchy is None:
        return
    generation = permanent_fleet_generation(initial_hierarchy)
    await store.add_config_revision(
        ConfigRevision(
            tenant_id=manifest.tenant_id,
            kind="permanent_fleet",
            ref="hierarchy",
            version=generation,
            payload={"hierarchy": initial_hierarchy},
            actor="manifest-apply",
        )
    )
