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

    from . import (
        adapters,
        admin,
        budgets,
        console,
        eval_routes,
        knowledge,
        memory,
        observability,
        personal,
        router,
        skills,
        workflows,
    )

    P = Depends(principal_dep)
    K = Depends(get_kernel)
    for module in (
        skills, router, adapters, workflows, admin, budgets, observability, console,
        eval_routes, personal, memory, knowledge,
    ):
        module.register(app, P, K)
