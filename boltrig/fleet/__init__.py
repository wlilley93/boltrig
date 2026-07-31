"""The Boltrig agent fleet (Epic FLT).

The fleet is the agent layer above the kernel: the permanent tier-1 Chief of
Staff (US-FLT-01) and tier-2 Department Heads (US-FLT-02), the spawn logic that
turns a task + skills into a bounded ephemeral agent (US-FLT-03/04), the
pluggable agent runtimes (P4), and the durable-execution seam over Hatchet (P6).

It depends on the kernel's frozen contracts and never modifies them; the kernel
stays unaware of the fleet and receives the reasoning-verb invoker via
``kernel.set_agent_invoker`` (US-KER-02). Everything is import- and offline-safe.
"""

from __future__ import annotations

from .anchor import (
    AnchorSweepOutcome,
    anchor_interval_from_env,
    run_anchor_forever,
    run_anchor_sweep_detailed,
)
from .retention import (
    retention_days_from_manifest,
    retention_interval_from_env,
    run_retention_forever,
)
from .chief_of_staff import ChiefOfStaff, Department
from .department_head import DepartmentHead
from .pump import WorkPump, build_org
from .result import AgentResult
from .runtime import (
    ClaudeApiRuntime,
    HermesRuntime,
    Runtime,
    ScriptRuntime,
    build_runtime,
)
from .spawn import (
    Spawner,
    build_spawner,
    make_agent_invoker,
    make_app_spawner,
)
from .workers import (
    HatchetExecutor,
    LocalDurableExecutor,
    register_workers,
)

__all__ = [
    # spawn
    "Spawner",
    "build_spawner",
    "make_app_spawner",
    "make_agent_invoker",
    # permanent agents + the delegation pump
    "ChiefOfStaff",
    "Department",
    "DepartmentHead",
    "WorkPump",
    "build_org",
    # runtimes
    "Runtime",
    "ScriptRuntime",
    "HermesRuntime",
    "ClaudeApiRuntime",
    "build_runtime",
    "AgentResult",
    # durable execution seam
    "register_workers",
    "LocalDurableExecutor",
    "HatchetExecutor",
    # periodic audit-rollup anchoring (COUNTY 9 D4)
    "AnchorSweepOutcome",
    "run_anchor_sweep_detailed",
    "run_anchor_forever",
    "anchor_interval_from_env",
    "run_retention_forever",
    "retention_interval_from_env",
    "retention_days_from_manifest",
]
