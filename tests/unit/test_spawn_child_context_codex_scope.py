"""The kernel scopes a read-only Codex leaf it orchestrates ([2026] VJS-CC-VJS 8).

A read-only Codex phase is scoped by a run + workspace; without a workspace the
runtime degrades ``no_read_only_phase_scope``. A scopeless caller (``/v1/spawn``
with no active workspace) still legitimately orchestrates a codex leaf, so the
orchestration layer (``Spawner._child_context``) scopes that leaf to its OWN run.
The phase is read-only, writes nothing, and its per-cell tree is already run/slot
isolated, so the run is a sufficient, self-contained scope. Non-codex runtimes are
untouched: a None workspace stays None.
"""

from __future__ import annotations

from boltrig.fleet.spawn import Spawner
from boltrig.models import AgentCapability, GrantSet
from boltrig.models.context import InvocationContext


def _capability(runtime: str) -> AgentCapability:
    return AgentCapability(
        name=f"{runtime}-worker",
        tenant_id="t1",
        runtime=runtime,
        supported_skills=["*"],
        max_depth=2,
        is_ephemeral=True,
        cost_tier="standard",
    )


def _spawner() -> Spawner:
    # RuntimeResolver/Spawner only store the kernel; a sentinel is enough (mirrors
    # test_runtime_resolver_codex).
    return Spawner(object())  # type: ignore[arg-type]


def _parent(workspace_id: str | None) -> InvocationContext:
    return InvocationContext(tenant_id="t1", run_id="parent-run", workspace_id=workspace_id)


def test_codex_leaf_without_workspace_is_scoped_to_its_own_run() -> None:
    child = _spawner()._child_context(
        "t1", "child-run", 1, _parent(None), _capability("codex"), [], GrantSet.of([])
    )
    assert child.workspace_id == "child-run"
    # Lineage is untouched: the child keeps its own run and the real parent link.
    assert child.run_id == "child-run"
    assert child.parent_run_id == "parent-run"


def test_codex_leaf_keeps_a_real_inherited_workspace() -> None:
    child = _spawner()._child_context(
        "t1", "child-run", 1, _parent("ws-real"), _capability("codex"), [], GrantSet.of([])
    )
    assert child.workspace_id == "ws-real"


def test_non_codex_leaf_workspace_stays_none() -> None:
    child = _spawner()._child_context(
        "t1", "child-run", 1, _parent(None), _capability("pi"), [], GrantSet.of([])
    )
    assert child.workspace_id is None
