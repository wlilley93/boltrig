"""WL-3: voluntary expression goes through the chokepoint, with no side door.

``familiar.express`` is the deliberate counterpart to the autonomic phenotype. Where the phenotype is a
downstream projection the surface reads (boltrig/emotion, EMO-1), a gesture is an ACTION, so it must be
a registered verb that is schema-bound, grant-checked, and audited like any other, and the ONLY thing
that writes the express channel the surface reads is that dispatched handler. These tests pin all of it:
an ungranted caller is denied and audited, bad params are rejected by the binding, a granted call is
dispatched and audited, and the express file appears ONLY after a successful dispatch (no direct
agent -> surface socket).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from boltrig.adapters.builtin.familiar import build as build_familiar
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantMissing,
    GrantSet,
    InvocationContext,
    SchemaValidationError,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

TENANT = "acme"


def _ctx(grants: list[str]) -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(grants),
        actor="ephemeral-1",
        actor_tier="ephemeral",
        run_id="run-wl3",
    )


async def _familiar_kernel() -> Kernel:
    store = InMemoryStore()
    # the tenant ceiling must also permit the verb (intersection with the caller's grants)
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["familiar.*"])))
    kernel = Kernel(store, blocking_verbs=set())
    await kernel.register_adapter(TENANT, build_familiar())
    return kernel


def _express_file(runtime_dir: pathlib.Path) -> pathlib.Path:
    return runtime_dir / "boltrig-express.json"


@pytest.mark.security
@pytest.mark.invariant("WL-3")
async def test_familiar_express_is_registered_with_a_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    kernel = await _familiar_kernel()
    # a granted call with a valid gesture dispatches and writes the channel
    out = await kernel.invoke(
        "familiar", "familiar.express", {"gesture": "greet", "intensity": 0.8},
        _ctx(["familiar.express"]),
    )
    assert out["gesture"] == "greet" and out["delivered"] is True
    rec = json.loads(_express_file(tmp_path).read_text())
    assert rec["gesture"] == "greet" and rec["v"] == 1
    # the record is a closed set of numbers + the gesture enum: no free text leaks to the surface
    assert set(rec) <= {"v", "gesture", "intensity", "ttl_s"}


@pytest.mark.security
@pytest.mark.invariant("WL-3")
async def test_ungranted_express_is_denied_audited_and_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    kernel = await _familiar_kernel()
    with pytest.raises(GrantMissing):
        await kernel.invoke("familiar", "familiar.express", {"gesture": "pulse"}, _ctx([]))
    # denied is still audited (SEC-16), and NO gesture reached the surface (no side door)
    events = await kernel.store.audit_query(TENANT)
    assert events[-1].verb == "familiar.express"
    assert events[-1].status == "grant_missing"
    assert not _express_file(tmp_path).exists()


@pytest.mark.security
@pytest.mark.invariant("WL-3")
async def test_bad_gesture_is_rejected_by_the_binding_and_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    kernel = await _familiar_kernel()
    # a gesture outside the enum fails schema validation BEFORE the handler runs (SEC-21)
    with pytest.raises(SchemaValidationError):
        await kernel.invoke(
            "familiar", "familiar.express", {"gesture": "detonate"}, _ctx(["familiar.express"])
        )
    assert not _express_file(tmp_path).exists()


@pytest.mark.security
@pytest.mark.invariant("WL-3")
async def test_a_dispatched_gesture_is_audited(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    kernel = await _familiar_kernel()
    await kernel.invoke(
        "familiar", "familiar.express", {"gesture": "celebrate"}, _ctx(["familiar.express"])
    )
    events = await kernel.store.audit_query(TENANT)
    row = events[-1]
    assert row.verb == "familiar.express"
    assert row.status == "ok"
    assert row.target_adapter == "familiar"
