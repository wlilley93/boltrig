"""The Boltrig agent fleet (Epic FLT).

The live fleet is a flat roster of durable, addressable tier-1 peers plus the
spawn logic that turns a bounded task and skills into a one-task ephemeral
agent. Named-peer sessions persist as mailbox logs and summaries; model
processes and ephemeral children may come and go.

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
from .named_agent import NamedAgent
from .agent_mailbox import AgentMailboxService
from .agent_turns import AgentTurnCoordinator, AgentTurnLeaseLost
from .pump import WorkPump, build_org
from .result import AgentResult
from .runtime import (
    Runtime,
    ScriptRuntime,
    UnavailableRuntime,
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
    "NamedAgent",
    "AgentMailboxService",
    "AgentTurnCoordinator",
    "AgentTurnLeaseLost",
    "WorkPump",
    "build_org",
    # runtimes
    "Runtime",
    "ScriptRuntime",
    "UnavailableRuntime",
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
