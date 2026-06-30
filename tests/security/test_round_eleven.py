"""Round Eleven - the run-events subscription endpoint (SEC-56, FR-EVT-03).

The Run drawer / live canvas subscribe to a run's event stream over
GET /v1/runs/{run_id}/events. It must be tenant-scoped: a run is streamable only
if it produced audited activity in the caller's tenant.

SEC-56     a run's event stream is tenant-scoped - another tenant cannot read it.
FR-EVT-03  the snapshot returns the events a run emitted (SSE frames), and an
           unknown run is a 404.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _hdr(tenant=T, grants="*", role="org-admin"):
    return {"x-boltrig-tenant": tenant, "x-boltrig-subject": "u",
            "x-boltrig-role": role, "x-boltrig-grants": grants}


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


@pytest.mark.invariant("FR-EVT-03")
async def test_unknown_run_is_404():
    k = await _kernel()
    c = TestClient(create_app(k))
    r = c.get("/v1/runs/does-not-exist/events", headers=_hdr())
    assert r.status_code == 404
