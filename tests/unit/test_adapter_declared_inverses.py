"""Adapters declare their (do, undo) pairs; registration composes them (FR-REV-01)."""

from __future__ import annotations

import pytest

from boltrig.adapters.builtin.ms_graph import MsGraphAdapter, _create_event_inverse
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


@pytest.fixture()
def scratch_registry(monkeypatch):
    import boltrig.kernel.effect_inverses as module

    monkeypatch.setattr(module, "_BUILDERS", {})
    return module


class _Annotated:
    id = "anno"
    version = "1"
    runtime = "script"
    activated = True

    def describe(self):
        return []

    def inverses(self):
        return {"anno.do": lambda p, o: ("anno.undo", {"ref": o["ref"]})}

    async def execute(self, verb, params, credential, context):
        raise AssertionError("never executed here")

    async def health(self):
        return "ok"


@pytest.mark.invariant("FR-REV-01")
async def test_registering_an_adapter_composes_its_declared_inverses(scratch_registry):
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    assert scratch_registry.inverse_for("anno.do", {}, {"ref": "r1"}) is None

    await k.register_adapter(T, _Annotated())

    assert scratch_registry.inverse_for("anno.do", {}, {"ref": "r1"}) == (
        "anno.undo", {"ref": "r1"}
    )


async def test_an_adapter_without_declarations_registers_nothing(scratch_registry):
    class _Plain(_Annotated):
        id = "plain"
        inverses = None  # the attribute exists but is not callable

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await Kernel(store).register_adapter(T, _Plain())

    assert scratch_registry._BUILDERS == {}


def test_create_event_inverse_builds_from_the_success_output():
    # The owner rides along from the create's params so the delete lands on
    # the same mailbox; the id comes from the OUTPUT (only it knows).
    assert _create_event_inverse({"owner": "a@b"}, {"id": "E1"}) == (
        "calendar.delete_event", {"event_id": "E1", "owner": "a@b"}
    )
    assert _create_event_inverse({}, {"id": "E2"}) == (
        "calendar.delete_event", {"event_id": "E2"}
    )
    # No id in the output: honestly not undoable, never a guessed delete.
    assert _create_event_inverse({"owner": "a@b"}, {}) is None


async def test_delete_event_handler_issues_the_graph_delete(monkeypatch):
    adapter = MsGraphAdapter()
    calls = []

    async def fake_request(client, method, url, **kw):
        calls.append((method, url, kw.get("expected")))
        return {}

    monkeypatch.setattr(adapter, "request", fake_request)
    handler = adapter._handlers()["calendar.delete_event"]

    out = await handler({"event_id": "AAMk=='/x", "owner": "who@acme.io"}, None, None)
    assert out.ok and out.output == {"status": "deleted"}
    out = await handler({"event_id": "E7"}, None, None)
    assert out.ok

    assert calls == [
        ("DELETE", "/users/who%40acme.io/events/AAMk%3D%3D%27%2Fx", (204,)),
        ("DELETE", "/me/events/E7", (204,)),
    ]
