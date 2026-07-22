"""Governed adapter suspension and removal - the inverse of activation (SEC-22).

A registered adapter previously had NO governed way out: once generated or
consumed it stayed forever, live or inert, short of hand-editing the store.
``control.adapter.deactivate`` suspends a live adapter - its published verb
rows leave the registry, so dispatch refuses exactly as it does for a
never-registered verb, and the review-gate flag flips back (re-activation
re-runs the gate). ``control.adapter.delete`` removes a NON-live adapter,
reversing exactly what registration + activation persisted (adapter row,
owned verbs/bindings, orphaned nouns, an unshared credential ref, the loader
instance) and refusing a live one - deactivate first, fail-closed.

Restart honesty: registration persists the consumer's url in the row's
``spec_ref``, and boot rehydrates control-plane-registered MCP consumers from
their rows (skipping loudly the rows it cannot reconstruct), so an adapter is
never a phantom row the control plane cannot govern. The lifecycle verbs also
fall back to the store record when the loader has no instance, so even a
non-rehydrated phantom row can be suspended and deleted.
"""

from __future__ import annotations

import json
import logging

import pytest

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.models import (
    AdapterFailure,
    AdapterRecord,
    BindingNotFound,
    GrantSet,
    HITLStateConflict,
    InvocationContext,
    PendingHuman,
    TargetType,
    TenantPermissions,
    Verb,
    VerbBinding,
)
from boltrig.store import InMemoryStore

T = "acme"

_TOOLS = [
    {
        "name": "ticket.read",
        "description": "read a ticket",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
    },
    {
        "name": "ticket.create",
        "description": "create a ticket",
        "inputSchema": {"type": "object"},
    },
]


class _Resp:
    """The httpx response shape the consumer reads: a status (typed error
    mapping), headers (session id / content type), and the JSON payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.headers: dict = {}

    def json(self) -> dict:
        return self._payload


class _FakeMcpServer:
    """Stands in for the external MCP server at the pinned-HTTP seam. Speaks the
    PLAIN convention (plain JSON 200 answers, no session), so the consumer's
    lazy handshake never fires here."""

    def __init__(self, tools: list[dict]) -> None:
        self.tools = tools

    async def post(self, url, json, headers):  # noqa: ANN001 - httpx-shaped stub
        if json.get("method") == "tools/list":
            return _Resp({"result": {"tools": self.tools}})
        return _Resp({"result": {"content": [{"type": "text", "text": "done"}]}})

    async def __aenter__(self) -> "_FakeMcpServer":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(
        T,
        build_control_plane_adapter(
            store, loader=k.loader, registry=k.registry, credentials=k.credentials
        ),
    )
    return k


def _ctx(grants: list[str], *, run_id: str = "run-1") -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(grants),
        actor="u",
        actor_tier="human",
        run_id=run_id,
        extra={"principal_role": "superadmin"},
    )


async def _approved(k: Kernel, verb: str, params: dict, *, run_id: str) -> dict:
    """Dispatch a high-consequence control verb through the full gate: first call
    is HELD (PendingHuman), then an approval releases the SAME call (SEC-14)."""
    with pytest.raises(PendingHuman) as exc:
        await k.invoke("control", verb, params, _ctx(["*"], run_id=run_id))
    req_id = exc.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    return await k.invoke(
        "control", verb, params, _ctx(["*"], run_id=run_id), approval_id=req_id
    )


async def _register(monkeypatch, k: Kernel, server: _FakeMcpServer) -> None:
    monkeypatch.setenv("MCP_TOK", "server-bearer")
    monkeypatch.setattr(
        "boltrig.adapters.egress.pinned_async_client", lambda url, timeout: server
    )
    out = await k.invoke(
        "control",
        "control.mcp_server.register",
        {"id": "ext-mcp", "url": "https://mcp.example.com", "credential_ref": "MCP_TOK"},
        _ctx(["*"]),
    )
    assert out["id"] == "ext-mcp" and out["activated"] is False


async def _live(monkeypatch, k: Kernel) -> _FakeMcpServer:
    server = _FakeMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)
    await _approved(k, "control.adapter.activate", {"adapter_id": "ext-mcp"}, run_id="a1")
    return server


@pytest.mark.invariant("SEC-22")
async def test_deactivate_suspends_execution_like_a_never_registered_verb(monkeypatch):
    k = await _kernel()
    await _live(monkeypatch, k)
    out = await k.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r1"))
    assert out == {"text": "done"}

    # the reference refusal: a verb that was never registered
    with pytest.raises(BindingNotFound) as unknown:
        await k.invoke("ext-mcp", "ext-mcp.ticket.ghost", {}, _ctx(["*"], run_id="r2"))

    out = await _approved(k, "control.adapter.deactivate", {"adapter_id": "ext-mcp"}, run_id="d1")
    assert out["activated"] is False
    assert set(out["verbs"]) == {"ext-mcp.ticket.read", "ext-mcp.ticket.create"}

    # dispatch now refuses the suspended verb EXACTLY like the never-registered one
    with pytest.raises(BindingNotFound) as suspended:
        await k.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r3"))
    assert str(suspended.value) == str(unknown.value).replace("ext-mcp.ticket.ghost", "ext-mcp.ticket.read")

    record = await k.store.get_adapter(T, "ext-mcp")
    assert record is not None and record.activated is False
    consumer = await k.loader.get(T, "ext-mcp")
    assert consumer is not None and consumer.activated is False  # inert again (SEC-22)

    # the state machine is not one-way: re-activation re-runs the gate and republishes
    out = await _approved(k, "control.adapter.activate", {"adapter_id": "ext-mcp"}, run_id="a2")
    assert out["activated"] is True
    out = await k.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r4"))
    assert out == {"text": "done"}


@pytest.mark.invariant("SEC-22")
async def test_deactivate_is_a_clean_noop_on_an_inert_adapter(monkeypatch):
    k = await _kernel()
    await _register(monkeypatch, k, _FakeMcpServer(list(_TOOLS)))

    out = await _approved(k, "control.adapter.deactivate", {"adapter_id": "ext-mcp"}, run_id="d1")

    assert out == {"id": "ext-mcp", "activated": False, "verbs": []}
    record = await k.store.get_adapter(T, "ext-mcp")
    assert record is not None and record.activated is False


@pytest.mark.invariant("SEC-22")
async def test_an_unknown_adapter_is_a_governed_not_found():
    k = await _kernel()

    for verb in (
        "control.adapter.activate",
        "control.adapter.deactivate",
        "control.adapter.delete",
    ):
        with pytest.raises(AdapterFailure) as caught:
            await k.invoke("control", verb, {"adapter_id": "ghost"}, _ctx(["*"]))
        assert caught.value.status_code == 404
    assert await k.hitl.list_pending(T) == []  # no approval work created for a 404


@pytest.mark.invariant("SEC-22")
async def test_delete_refuses_a_live_adapter(monkeypatch):
    k = await _kernel()
    await _live(monkeypatch, k)

    with pytest.raises(PendingHuman) as held:
        await k.invoke(
            "control", "control.adapter.delete", {"adapter_id": "ext-mcp"}, _ctx(["*"])
        )
    req_id = held.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    with pytest.raises(AdapterFailure) as caught:
        await k.invoke(
            "control", "control.adapter.delete", {"adapter_id": "ext-mcp"},
            _ctx(["*"]), approval_id=req_id,
        )

    assert caught.value.status_code == 409
    assert "deactivate" in str(caught.value)
    # nothing was torn down: the adapter is still live and dispatchable
    record = await k.store.get_adapter(T, "ext-mcp")
    assert record is not None and record.activated is True
    out = await k.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r1"))
    assert out == {"text": "done"}


@pytest.mark.invariant("SEC-22")
async def test_delete_reverses_registration_exactly(monkeypatch):
    k = await _kernel()
    store = k.store
    # a second tenant with the same control-plane baseline but no "ext-mcp":
    # the post-delete raw state must match it exactly
    await k.register_adapter(
        "other",
        build_control_plane_adapter(
            store, loader=k.loader, registry=k.registry, credentials=k.credentials
        ),
    )
    await _live(monkeypatch, k)
    assert (await store.get_credential_ref(T, "ext-mcp-mcp-token")) is not None
    assert (await k.credentials.resolve_for_adapter(T, "ext-mcp")) is not None
    await _approved(k, "control.adapter.deactivate", {"adapter_id": "ext-mcp"}, run_id="d1")

    out = await _approved(k, "control.adapter.delete", {"adapter_id": "ext-mcp"}, run_id="x1")

    assert out["deleted"] is True
    assert out["credential_ref"] == "ext-mcp-mcp-token"
    # every row registration + activation persisted is gone
    assert await store.get_adapter(T, "ext-mcp") is None
    assert await store.get_verb(T, "ext-mcp.ticket.read") is None
    assert await store.get_binding(T, "ext-mcp.ticket.read") is None
    assert await store.get_noun(T, "ext-mcp") is None  # orphaned by the removal
    assert await store.get_credential_ref(T, "ext-mcp-mcp-token") is None
    assert await k.credentials.resolve_for_adapter(T, "ext-mcp") is None
    assert k.loader.peek(T, "ext-mcp") is None
    # raw state matches a tenant that never registered the adapter
    assert sorted(v.id for v in await store.list_verbs(T)) == sorted(
        v.id for v in await store.list_verbs("other")
    )
    assert [a.id for a in await store.list_adapters(T)] == [
        a.id for a in await store.list_adapters("other")
    ]


@pytest.mark.invariant("SEC-22")
async def test_delete_refuses_the_control_adapter_itself():
    k = await _kernel()

    with pytest.raises(PendingHuman) as held:
        await k.invoke(
            "control", "control.adapter.delete", {"adapter_id": "control"}, _ctx(["*"])
        )
    req_id = held.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    with pytest.raises(AdapterFailure) as caught:
        await k.invoke(
            "control", "control.adapter.delete", {"adapter_id": "control"},
            _ctx(["*"]), approval_id=req_id,
        )

    assert caught.value.status_code == 409
    # the refusal came THROUGH the control adapter's own dispatch, so the
    # reserved-id guard never suspends the control plane itself
    assert k.loader.peek(T, "control") is not None


# --- restart honesty: persisted rows must not be phantoms --------------------
async def _restart_kernel(store: InMemoryStore) -> Kernel:
    """A fresh kernel on the SAME store - the restart shape: an empty loader,
    empty in-memory credential bindings, durable rows intact."""
    k = Kernel(store)
    await k.register_adapter(
        T,
        build_control_plane_adapter(
            store, loader=k.loader, registry=k.registry, credentials=k.credentials
        ),
    )
    return k


@pytest.mark.invariant("SEC-22")
async def test_registration_persists_the_url_for_boot_rehydration(monkeypatch):
    k = await _kernel()
    await _register(monkeypatch, k, _FakeMcpServer(list(_TOOLS)))

    record = await k.store.get_adapter(T, "ext-mcp")

    assert record is not None
    assert record.module_ref == "boltrig.adapters.mcp_consumer"
    # spec_ref is the rehydration source: the url plus the reviewed egress
    # posture, as JSON (the flag defaults off - the guarded posture)
    assert json.loads(record.spec_ref) == {
        "url": "https://mcp.example.com",
        "allow_internal": False,
    }


@pytest.mark.invariant("SEC-61")
async def test_the_reviewed_allow_internal_flag_persists_and_rehydrates():
    """An operator-vetted INTERNAL server registers with allow_internal (the
    SEC-61 waiver, itself behind the SEC-22 gate); the flag persists in
    spec_ref and a restarted kernel rebuilds the consumer with it ON."""
    from boltrig.api.bootstrap import _rehydrate_store_adapters

    k1 = await _kernel()
    out = await k1.invoke(
        "control",
        "control.mcp_server.register",
        {"id": "ext-mcp", "url": "http://opbox-kernel:8088/mcp", "allow_internal": True},
        _ctx(["*"]),
    )
    assert out["activated"] is False  # still inert pending the review gate

    record = await k1.store.get_adapter(T, "ext-mcp")
    assert record is not None
    assert json.loads(record.spec_ref) == {
        "url": "http://opbox-kernel:8088/mcp",
        "allow_internal": True,
    }

    k2 = await _restart_kernel(k1.store)
    await _rehydrate_store_adapters(k2, T)

    consumer = k2.loader.peek(T, "ext-mcp")
    assert consumer is not None
    assert consumer._transport.allow_internal is True  # the waiver survived restart


@pytest.mark.invariant("SEC-61")
async def test_a_pre_flag_plain_url_row_rehydrates_with_the_guarded_default():
    """Backward compatibility: rows written before the egress flag existed hold
    the plain url STRING in spec_ref. They rehydrate with allow_internal OFF -
    an old row can never silently gain the internal waiver."""
    from boltrig.api.bootstrap import _rehydrate_store_adapters

    k = await _kernel()
    await k.store.upsert_adapter(
        AdapterRecord(
            id="legacy-mcp",
            tenant_id=T,
            version="1",
            runtime="mcp",
            source="manual",
            module_ref="boltrig.adapters.mcp_consumer",
            spec_ref="http://opbox-kernel:8088/mcp",  # the pre-flag plain string
        )
    )

    await _rehydrate_store_adapters(k, T)

    consumer = k.loader.peek(T, "legacy-mcp")
    assert consumer is not None
    assert consumer._url == "http://opbox-kernel:8088/mcp"
    assert consumer._transport.allow_internal is False  # the guarded default


@pytest.mark.invariant("SEC-22")
async def test_boot_rehydrates_a_control_plane_registered_consumer(monkeypatch):
    from boltrig.api.bootstrap import _rehydrate_store_adapters

    k1 = await _kernel()
    await _live(monkeypatch, k1)
    k2 = await _restart_kernel(k1.store)
    assert k2.loader.peek(T, "ext-mcp") is None  # the phantom-row gap

    await _rehydrate_store_adapters(k2, T)

    consumer = k2.loader.peek(T, "ext-mcp")
    assert consumer is not None
    assert consumer.activated is True  # the persisted review gate stands (SEC-22)
    # the default credential-id convention re-bound from its persisted ref row
    resolved = await k2.credentials.resolve_for_adapter(T, "ext-mcp")
    assert resolved is not None and resolved.id == "ext-mcp-mcp-token"
    # and the rehydrated instance executes through the chokepoint
    out = await k2.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r9"))
    assert out == {"text": "done"}


@pytest.mark.invariant("SEC-22")
async def test_boot_skips_rows_it_cannot_reconstruct_loudly(caplog):
    from boltrig.api.bootstrap import _rehydrate_store_adapters

    k = await _kernel()
    store = k.store
    # a consumer row registered before the url was persisted: unrecoverable
    await store.upsert_adapter(
        AdapterRecord(
            id="url-less",
            tenant_id=T,
            version="1",
            runtime="mcp",
            source="manual",
            module_ref="boltrig.adapters.mcp_consumer",
        )
    )
    # a generated adapter: no honest reconstruction (its spec was never kept)
    await store.upsert_adapter(
        AdapterRecord(
            id="gen-1",
            tenant_id=T,
            version="1",
            runtime="script",
            source="generated",
            module_ref="boltrig.adapters.generator",
        )
    )

    with caplog.at_level(logging.WARNING, logger="boltrig.bootstrap"):
        await _rehydrate_store_adapters(k, T)

    assert k.loader.peek(T, "url-less") is None
    assert k.loader.peek(T, "gen-1") is None
    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("url-less" in message and "spec_ref" in message for message in warnings)
    assert any("gen-1" in message for message in warnings)


@pytest.mark.invariant("SEC-22")
async def test_lifecycle_verbs_govern_a_store_only_phantom_row(monkeypatch):
    """No rehydration after the restart: deactivate/delete must still govern the
    row via the store fallback in the approval context."""
    k1 = await _kernel()
    await _live(monkeypatch, k1)
    k2 = await _restart_kernel(k1.store)  # restart WITHOUT rehydration
    assert k2.loader.peek(T, "ext-mcp") is None

    out = await _approved(k2, "control.adapter.deactivate", {"adapter_id": "ext-mcp"}, run_id="pd1")
    assert out["activated"] is False
    assert set(out["verbs"]) == {"ext-mcp.ticket.read", "ext-mcp.ticket.create"}

    out = await _approved(k2, "control.adapter.delete", {"adapter_id": "ext-mcp"}, run_id="px1")
    assert out["deleted"] is True
    assert out["credential_ref"] == "ext-mcp-mcp-token"  # derived after the restart

    store = k2.store
    assert await store.get_adapter(T, "ext-mcp") is None
    assert await store.get_verb(T, "ext-mcp.ticket.read") is None
    assert await store.get_noun(T, "ext-mcp") is None
    assert await store.get_credential_ref(T, "ext-mcp-mcp-token") is None


# --- approval-gated activation: no silent re-pend, phantom activation --------
@pytest.mark.invariant("SEC-14")
async def test_a_consumed_approval_fails_loudly_instead_of_repending(monkeypatch):
    """The live infinite-pend repro: retry #1 spends the approval and then the
    activation FAILS (here: a verb ownership conflict); retry #2 with the spent
    approval_id previously returned 202 with a FRESH pend forever. A spent
    approval must fail loudly - the caller inspects state, not re-approves."""
    k = await _kernel()
    await _register(monkeypatch, k, _FakeMcpServer(list(_TOOLS)))
    # a verb the activation would publish is already owned by another target:
    # discovery succeeds, the publish refuses, the approval is already spent
    await k.store.upsert_verb(
        Verb(id="ext-mcp.ticket.read", tenant_id=T, noun_id="ext-mcp",
             input_schema={}, output_schema={})
    )
    await k.store.upsert_binding(
        VerbBinding(verb_id="ext-mcp.ticket.read", tenant_id=T,
                    target_type=TargetType.ADAPTER, target_ref="other-adapter")
    )

    params = {"adapter_id": "ext-mcp"}
    with pytest.raises(PendingHuman) as held:
        await k.invoke("control", "control.adapter.activate", params, _ctx(["*"], run_id="a1"))
    req_id = held.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    with pytest.raises(AdapterFailure) as conflict:
        await k.invoke(
            "control", "control.adapter.activate", params,
            _ctx(["*"], run_id="a1"), approval_id=req_id,
        )
    assert conflict.value.status_code == 409  # activation refused; approval spent

    with pytest.raises(HITLStateConflict) as spent:
        await k.invoke(
            "control", "control.adapter.activate", params,
            _ctx(["*"], run_id="a1"), approval_id=req_id,
        )
    assert spent.value.status_code == 409
    assert spent.value.reason == "hitl_state_conflict"
    assert await k.hitl.list_pending(T) == []  # the retry created NO new pend


@pytest.mark.invariant("SEC-22")
async def test_phantom_row_activate_rehydrates_on_demand(monkeypatch):
    """A rehydratable phantom row (spec_ref persisted, loader empty - another
    replica's registration or a post-boot registration elsewhere) activates
    through the full gate: pend on the store-view context, approve, retry ->
    on-demand rebuild -> discovery -> verbs published -> adapter live."""
    k1 = await _kernel()
    await _register(monkeypatch, k1, _FakeMcpServer(list(_TOOLS)))
    k2 = await _restart_kernel(k1.store)  # restart shape WITHOUT boot rehydration
    assert k2.loader.peek(T, "ext-mcp") is None

    out = await _approved(k2, "control.adapter.activate", {"adapter_id": "ext-mcp"}, run_id="a1")

    assert out["activated"] is True
    assert set(out["verbs"]) == {"ext-mcp.ticket.read", "ext-mcp.ticket.create"}
    consumer = k2.loader.peek(T, "ext-mcp")
    assert consumer is not None and consumer.activated is True
    record = await k2.store.get_adapter(T, "ext-mcp")
    assert record is not None and record.activated is True
    out = await k2.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r9"))
    assert out == {"text": "done"}


@pytest.mark.invariant("SEC-22")
async def test_phantom_row_without_a_url_fails_loudly_and_typed():
    """An unreconstructible phantom (a pre-spec_ref row, or a shape with no
    honest rebuild) fails the activate pend with a typed 409 BEFORE any
    approval work exists - never an infinite pend loop - while the lifecycle
    verbs stay the repair path."""
    k = await _kernel()
    await k.store.upsert_adapter(
        AdapterRecord(
            id="old-mcp",
            tenant_id=T,
            version="1",
            runtime="mcp",
            source="manual",
            module_ref="boltrig.adapters.mcp_consumer",
        )
    )

    with pytest.raises(AdapterFailure) as caught:
        await k.invoke(
            "control", "control.adapter.activate", {"adapter_id": "old-mcp"}, _ctx(["*"])
        )

    assert caught.value.status_code == 409
    assert caught.value.reason == "control_adapter_unrehydratable"
    assert await k.hitl.list_pending(T) == []
    # the repair path still governs the row
    out = await _approved(k, "control.adapter.delete", {"adapter_id": "old-mcp"}, run_id="x1")
    assert out["deleted"] is True
