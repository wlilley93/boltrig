"""GET /v1/budgets: the tenant's budgets with live burn-down, tenant-isolated.

A read-only surface over the existing Budget store (the budgets table + the
consume_budget accumulators), so the cost-budgets UI has something to render.
Tenant isolation is the load-bearing property here.
"""

from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import Budget, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
OTHER = "globex"


def _client():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    store.set_tenant_permissions(TenantPermissions(OTHER, GrantSet.of(["*"])))
    store.set_budget(
        Budget(id="tenant", tenant_id=T, scope_type="tenant", token_limit=1000,
               spent_tokens=250, cost_limit_micros=5_000_000, spent_micros=1_000_000)
    )
    store.set_budget(
        Budget(id="wf-onboarding", tenant_id=T, scope_type="workflow", token_limit=500,
               spent_tokens=100)
    )
    # a different tenant's budget must never appear in T's view
    store.set_budget(Budget(id="tenant", tenant_id=OTHER, scope_type="tenant", token_limit=9))
    k = Kernel(store)
    return TestClient(create_app(k, platform={}))


def _h(sub="alice", role="org-admin"):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": sub, "x-boltrig-role": role,
            "x-boltrig-grants": "*"}


def test_budgets_are_tenant_isolated_with_burndown():
    c = _client()
    body = c.get("/v1/budgets", headers=_h()).json()
    ids = {b["id"] for b in body["budgets"]}
    assert "tenant" in ids and "wf-onboarding" in ids
    # the other tenant's "tenant" budget (limit 9) is not leaked - ours has limit 1000
    tb = next(b for b in body["budgets"] if b["id"] == "tenant")
    assert tb["token_limit"] == 1000 and tb["spent_tokens"] == 250
    assert tb["cost_limit_micros"] == 5_000_000 and tb["spent_micros"] == 1_000_000
    assert tb["hard_stop"] is True


def test_budgets_other_tenant_sees_only_its_own():
    c = _client()
    body = c.get(
        "/v1/budgets",
        headers={"x-boltrig-tenant": OTHER, "x-boltrig-subject": "bob",
                 "x-boltrig-role": "org-admin", "x-boltrig-grants": "*"},
    ).json()
    assert [b["token_limit"] for b in body["budgets"]] == [9]
