"""Platform HTTP surface (Round Three): authoring studios, admin console,
observability, eval, personal agents, memory.

Split by resource from the former monolithic platform_routes.py. Every route is
a thin layer over a service (C2); authoring/admin require a permitting role and
are audited (C3, SEC-32); insight is scope-filtered (C5, SEC-33); anything that
executes runs the kernel chokepoint under the caller's grants (C4, SEC-29/30).
Services are read from ``app.state.platform``.
"""

from __future__ import annotations

# Compat re-export: safe_consequence was historically importable from this module.
from boltrig.config.control_plane import safe_consequence  # noqa: F401


def register_platform_routes(app, *, principal_dep, get_kernel) -> None:
    from fastapi import Depends
    from boltrig.kernel.call_routes import register_call_routes
    from boltrig.kernel.device_routes import register_device_routes

    from . import (
        addons,
        adapters,
        admin,
        agent_capabilities,
        artifacts,
        backup_status,
        bifrost_models,
        birth_profile,
        budgets,
        chat_model_choices,
        console,
        device_inventory,
        eval_routes,
        hitl_policy,
        knowledge,
        integrations,
        mcp_servers,
        memory,
        model_endpoints,
        model_profiles,
        observability,
        personal,
        permanent_fleet,
        privacy_policy,
        router,
        skills,
        spawn_rules,
        work,
        workflows,
    )

    P = Depends(principal_dep)
    K = Depends(get_kernel)
    for module in (
        skills, router, addons, adapters, mcp_servers, agent_capabilities, workflows, admin, artifacts, bifrost_models, birth_profile,
        backup_status, budgets, observability, console, device_inventory,
        eval_routes, hitl_policy, personal, permanent_fleet, privacy_policy, memory, knowledge, integrations, model_endpoints, model_profiles, chat_model_choices,
        spawn_rules, work,
    ):
        module.register(app, P, K)
    register_call_routes(app, principal_dep=principal_dep, get_kernel=get_kernel)
    register_device_routes(app, principal_dep=principal_dep, get_kernel=get_kernel)
