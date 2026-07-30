"""Round Five HTTP surface: the memory verbs + scoped reads (Epic MEM/RCL/LRN/MUI).

recall / remember / improve / forget / ingest run through the kernel chokepoint
by invoking the ``memory.*`` verbs - so grant check + audit apply and the MemoryAdapter
enforces owner-scope (SEC-40). The caller's permitted owner-scopes are computed
from the Principal (rbac.memory_owner_scopes) and carried in the invocation
context, so the kernel - not the engine - is the boundary. The facts/ingestions
reads are scope-filtered (C5). These are also drivable headless / via MCP since a
PAT or bearer yields the same Principal (Round Four HEAD).
"""

from __future__ import annotations

from fastapi import Depends

from boltrig.kernel.memory_mutation_routes import (
    memory_scopes,
    register_memory_mutation_routes,
)


def register_memory_routes(app, *, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)
    register_memory_mutation_routes(app, P, K)

    from .memory_read_routes import register_memory_read_routes

    register_memory_read_routes(app, P=P, K=K, scopes=memory_scopes)
