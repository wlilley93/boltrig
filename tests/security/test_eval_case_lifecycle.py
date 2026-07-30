"""Recoverable, governed evaluation-case archival contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet.eval import EvalRunner
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    EvalCase,
    EvalCaseArchived,
    EvalRun,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "eval-case-lifecycle"


def _case(
    case_id: str,
    *,
    target_ref: str = "review",
    is_active: bool = True,
) -> EvalCase:
    return EvalCase(
        id=case_id,
        tenant_id=T,
        target_kind="skill",
        target_ref=target_ref,
        input={"task": f"evaluate {case_id}"},
        assertions={"must_not_call": ["record.delete"]},
        labels=["regression"],
        is_active=is_active,
    )


def _context(label: str) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id=f"run-{label}",
        extra={"principal_role": "org-admin", "principal_scope": {"all": True}},
    )


def _headers(*, role: str = "org-admin") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
    }


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store, loader=kernel.loader, registry=kernel.registry
        ),
    )
    return kernel


async def _approved(kernel: Kernel, verb: str, params: dict) -> dict:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    await kernel.hitl.answer(
        T, held.value.hitl_request_id, "approve", "reviewer"
    )
    return await kernel.invoke(
        "control",
        verb,
        params,
        _context(verb),
        approval_id=held.value.hitl_request_id,
    )


class _NoSpawn:
    def __init__(self) -> None:
        self.calls = 0

    async def spawn(self, *args, **kwargs):
        self.calls += 1
        return {}


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run_case(self, case, *, grants, actor, context=None):
        self.calls += 1
        return EvalRun(
            id=f"http-run-{self.calls}",
            tenant_id=case.tenant_id,
            case_id=case.id,
            passed=True,
            score=1.0,
            run_id=f"fleet-run-{self.calls}",
            detail={"checks": {"safe": True}},
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-18")
async def test_author_inventory_retains_archived_cases_and_lifecycle_is_governed() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_eval_case(_case("active"))
    await kernel.store.upsert_eval_case(_case("archived"))
    await kernel.store.set_eval_case_active(T, "archived", False)
    client = TestClient(create_app(kernel, platform={}))

    inventory = client.get("/v1/eval/cases", headers=_headers())
    assert inventory.status_code == 200
    assert [
        (row["id"], row["status"], row["is_active"])
        for row in inventory.json()["cases"]
    ] == [
        ("active", "active", True),
        ("archived", "archived", False),
    ]

    pending = client.post(
        "/v1/eval/cases/active/archive", headers=_headers()
    )
    assert pending.status_code == 202
    assert pending.json()["status"] == "pending_human"
    assert client.get(
        "/v1/eval/cases", headers=_headers(role="member")
    ).status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-18")
async def test_archive_preserves_fixture_and_history_and_blocks_every_run_path() -> None:
    kernel = await _kernel()
    case = _case("recoverable")
    await kernel.store.upsert_eval_case(case)
    historical = EvalRun(
        id="historical",
        tenant_id=T,
        case_id=case.id,
        passed=False,
        score=0.5,
        run_id="old-fleet-run",
        detail={"checks": {"old": False}},
    )
    await kernel.store.add_eval_run(historical)

    archived_output = await _approved(
        kernel, "control.eval_case.archive", {"id": case.id}
    )
    assert archived_output == {
        "id": case.id,
        "eval_case_status": "archived",
    }
    archived = await kernel.store.get_eval_case(T, case.id)
    assert archived is not None
    assert archived.is_active is False
    assert archived.input == case.input
    assert archived.assertions == case.assertions
    assert archived.labels == case.labels
    assert [run.id for run in await kernel.store.list_eval_runs(T, case.id)] == [
        historical.id
    ]

    # Fixture editing remains possible, but is not a lifecycle side door.
    edited_output = await _approved(
        kernel,
        "control.eval_case.upsert",
        {
            "id": case.id,
            "target_kind": "skill",
            "target_ref": "review-v2",
            "input": case.input,
            "assertions": case.assertions,
            "labels": case.labels,
        },
    )
    assert edited_output["eval_case_status"] == "archived"
    edited = await kernel.store.get_eval_case(T, case.id)
    assert edited is not None
    assert edited.target_ref == "review-v2"
    assert edited.is_active is False

    no_spawn = _NoSpawn()
    with pytest.raises(EvalCaseArchived):
        await EvalRunner(kernel, no_spawn).run_case(
            case, grants=GrantSet.of(["*"]), actor="author"
        )
    assert no_spawn.calls == 0

    route_runner = _RecordingRunner()
    client = TestClient(create_app(kernel, platform={"eval": route_runner}))
    blocked = client.post(
        "/v1/eval/run",
        headers=_headers(),
        json={"case_id": case.id},
    )
    assert blocked.status_code == 409
    assert blocked.json() == {"error": "eval_case_archived"}
    assert route_runner.calls == 0

    restored_output = await _approved(
        kernel, "control.eval_case.restore", {"id": case.id}
    )
    assert restored_output == {
        "id": case.id,
        "eval_case_status": "active",
    }
    allowed = client.post(
        "/v1/eval/run",
        headers=_headers(),
        json={"case_id": case.id},
    )
    assert allowed.status_code == 200
    assert allowed.json()["passed"] is True
    assert route_runner.calls == 1
    assert [run.id for run in await kernel.store.list_eval_runs(T, case.id)] == [
        historical.id
    ]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-18")
async def test_eval_case_lifecycle_approval_is_bound_to_exact_fixture_state() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_eval_case(_case("mutable"))
    params = {"id": "mutable"}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control",
            "control.eval_case.archive",
            params,
            _context("archive"),
        )
    await kernel.store.upsert_eval_case(
        _case("mutable", target_ref="changed-after-review")
    )
    await kernel.hitl.answer(
        T, held.value.hitl_request_id, "approve", "reviewer"
    )

    with pytest.raises(PendingHuman) as rebound:
        await kernel.invoke(
            "control",
            "control.eval_case.archive",
            params,
            _context("archive"),
            approval_id=held.value.hitl_request_id,
        )
    assert rebound.value.hitl_request_id != held.value.hitl_request_id
    current = await kernel.store.get_eval_case(T, "mutable")
    assert current is not None
    assert current.is_active is True
    assert current.target_ref == "changed-after-review"
