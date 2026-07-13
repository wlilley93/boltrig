"""Round Eleven - the run-events subscription endpoint (SEC-56, FR-EVT-03).

The Run drawer / live canvas subscribe to a run's event stream over
GET /v1/runs/{run_id}/events. It must be scoped: a run is streamable only if it
produced audited activity in the caller's tenant and is visible to the caller's
department/workspace scope.

SEC-56     a run's event stream is tenant/scope-scoped - another tenant or
           same-tenant scoped caller cannot read out-of-scope raw events.
FR-EVT-03  the snapshot returns the events a run emitted (SSE frames), and an
           unknown run is a 404.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions, WorkItem, WorkStatus
from boltrig.store import InMemoryStore

T = "acme"


class _RunScopeStore(InMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.work_list_calls = 0
        self.run_lookup_calls: list[str] = []

    async def list_work_items(self, *args, **kwargs):
        self.work_list_calls += 1
        return await super().list_work_items(*args, **kwargs)

    async def get_work_item_by_run_id(self, tenant_id, run_id):
        self.run_lookup_calls.append(run_id)
        return await super().get_work_item_by_run_id(tenant_id, run_id)


async def _kernel(store: InMemoryStore | None = None) -> Kernel:
    store = store or InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _hdr(tenant=T, grants="*", role="org-admin", departments=""):
    return {"x-boltrig-tenant": tenant, "x-boltrig-subject": "u",
            "x-boltrig-role": role, "x-boltrig-grants": grants,
            "x-boltrig-departments": departments}


def _frames(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("data:")]


@pytest.mark.security
@pytest.mark.invariant("SEC-56")
async def test_run_events_are_tenant_scoped():
    k = await _kernel()
    c = TestClient(create_app(k))
    # drive a verb under a specific run in tenant T -> emits events + audit
    r = c.post("/v1/invoke", headers=_hdr(),
               json={"noun": "ticket", "verb": "ticket.create",
                     "params": {"title": "x"}, "context": {"run_id": "run-Z"}})
    assert r.json()["status"] == "ok"

    # the owning tenant can read its run's event snapshot
    own = c.get("/v1/runs/run-Z/events", headers=_hdr())
    assert own.status_code == 200
    frames = _frames(own.text)
    assert any("tool_call" in f for f in frames)
    assert any("tool_result" in f for f in frames)

    # a DIFFERENT tenant cannot - the run is not in its audit scope (404, no leak)
    other = c.get("/v1/runs/run-Z/events", headers=_hdr(tenant="rival"))
    assert other.status_code == 404
    assert "tool_call" not in other.text


@pytest.mark.security
@pytest.mark.invariant("SEC-56")
async def test_same_tenant_scoped_user_cannot_read_unowned_run_events():
    k = await _kernel()
    c = TestClient(create_app(k))
    secret = "same tenant raw event should stay private"
    r = c.post("/v1/invoke", headers=_hdr(),
               json={"noun": "ticket", "verb": "ticket.create",
                     "params": {"title": secret}, "context": {"run_id": "run-private"}})
    assert r.json()["status"] == "ok"

    scoped = c.get(
        "/v1/runs/run-private/events",
        headers=_hdr(grants="", role="engineer", departments="engineering"),
    )
    assert scoped.status_code == 404
    assert secret not in scoped.text


@pytest.mark.security
@pytest.mark.invariant("SEC-56")
async def test_department_scoped_user_can_read_visible_work_run_events():
    store = _RunScopeStore()
    k = await _kernel(store)
    await k.store.create_work_item(
        WorkItem(
            id="w-eng",
            tenant_id=T,
            source="internal",
            intent="engineering task",
            confidence=0.9,
            convergent=True,
            status=WorkStatus.PENDING,
            owner_member="engineering",
            hatchet_run_id="run-eng",
        )
    )
    c = TestClient(create_app(k))
    r = c.post("/v1/invoke", headers=_hdr(),
               json={"noun": "ticket", "verb": "ticket.create",
                     "params": {"title": "engineering"}, "context": {"run_id": "run-eng"}})
    assert r.json()["status"] == "ok"

    scoped = c.get(
        "/v1/runs/run-eng/events",
        headers=_hdr(grants="", role="engineer", departments="engineering"),
    )
    assert scoped.status_code == 200
    assert any("tool_call" in f for f in _frames(scoped.text))
    assert store.run_lookup_calls == ["run-eng"]
    assert store.work_list_calls == 0


@pytest.mark.invariant("FR-EVT-03")
async def test_unknown_run_is_404():
    k = await _kernel()
    c = TestClient(create_app(k))
    r = c.get("/v1/runs/does-not-exist/events", headers=_hdr())
    assert r.status_code == 404
