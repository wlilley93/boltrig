"""Budget mutations are governed, tenant-bound, and store-consistent."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AdapterFailure,
    Budget,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

TENANT = "acme"


def _context(*, role: str = "superadmin") -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(["*"]),
        actor="admin",
        actor_tier="human",
        run_id="budget-run",
        extra={"principal_role": role},
    )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(
        TENANT,
        build_control_plane_adapter(
            store,
            loader=kernel.loader,
            registry=kernel.registry,
        ),
    )
    return kernel


async def _approved(
    kernel: Kernel, verb: str, params: dict, *, context: InvocationContext | None = None
) -> dict:
    context = context or _context()
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, context)
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(TENANT, request_id, "approve", "reviewer")
    return await kernel.invoke(
        "control", verb, params, context, approval_id=request_id
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-143")
async def test_budget_policy_preserves_usage_and_reset_is_selective():
    kernel = await _kernel()
    await kernel.store.upsert_budget_policy(
        Budget(
            id=TENANT,
            tenant_id=TENANT,
            scope_type="tenant",
            token_limit=100,
            cost_limit_micros=200,
            spent_tokens=40,
            spent_micros=80,
        )
    )

    upserted = await _approved(
        kernel,
        "control.budget.upsert",
        {
            "scope_type": "tenant",
            "scope_id": TENANT,
            "token_limit": 500,
            "cost_limit_micros": 900,
            "hard_stop": False,
            "window": "monthly",
        },
    )
    assert upserted["budget"] == {
        "id": TENANT,
        "scope_type": "tenant",
        "window": "monthly",
        "hard_stop": False,
        "token_limit": 500,
        "spent_tokens": 40,
        "cost_limit_micros": 900,
        "spent_micros": 80,
    }

    reset = await _approved(
        kernel,
        "control.budget.reset",
        {
            "scope_type": "tenant",
            "scope_id": TENANT,
            "reason": "monthly close",
            "reset_tokens": True,
            "reset_cost": False,
        },
    )
    assert reset["reason"] == "monthly close"
    assert reset["budget"]["spent_tokens"] == 0
    assert reset["budget"]["spent_micros"] == 80


@pytest.mark.security
@pytest.mark.invariant("SEC-143")
async def test_budget_http_mutations_are_held_and_tenant_bound():
    kernel = await _kernel()
    client = TestClient(create_app(kernel))
    headers = {
        "x-boltrig-tenant": TENANT,
        "x-boltrig-subject": "admin",
        "x-boltrig-role": "org-admin",
    }
    body = {"token_limit": 1000, "hard_stop": True, "window": "daily"}

    held = client.put(f"/v1/budgets/tenant/{TENANT}", json=body, headers=headers)
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    await kernel.hitl.answer(TENANT, request_id, "approve", "reviewer")
    applied = client.put(
        f"/v1/budgets/tenant/{TENANT}",
        json={**body, "approval_id": request_id},
        headers=headers,
    )
    assert applied.status_code == 200
    assert applied.json()["budget"]["token_limit"] == 1000

    cross_tenant = client.put(
        "/v1/budgets/tenant/other",
        json=body,
        headers=headers,
    )
    assert cross_tenant.status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-143")
async def test_budget_control_verbs_reject_non_admin_even_with_grants():
    kernel = await _kernel()
    params = {
        "scope_type": "tenant",
        "scope_id": TENANT,
        "token_limit": 100,
    }
    context = _context(role="member")
    with pytest.raises(AdapterFailure) as denied:
        await kernel.invoke(
            "control",
            "control.budget.upsert",
            params,
            context,
        )
    assert denied.value.status_code == 403
