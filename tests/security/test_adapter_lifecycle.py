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

import asyncio
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
    utcnow,
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

_GENERATED_SPEC = {
    "openapi": "3.0.0",
    "info": {
        "title": "Durable generated adapter",
        "version": "1.0.0",
        "x-private-note": "unused-openapi-secret-canary",
    },
    "servers": [{"url": "https://generated.example.test/api"}],
    "components": {
        "securitySchemes": {
            "unused": {
                "type": "apiKey",
                "in": "header",
                "name": "x-key",
                "x-secret-example": "unused-openapi-secret-canary",
            }
        }
    },
    "paths": {
        "/things": {
            "get": {
                "operationId": "thing.list",
                "summary": "List things",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "example": {
                                        "token": "unused-openapi-secret-canary"
                                    },
                                    "x-private-example": (
                                        "unused-openapi-secret-canary"
                                    ),
                                    "properties": {
                                        "example": {
                                            "type": "string",
                                            "default": (
                                                "unused-openapi-secret-canary"
                                            ),
                                        }
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}


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


class _BlockingMcpServer(_FakeMcpServer):
    """Deterministic remote-I/O gate for MCP config-generation races."""

    def __init__(self, tools: list[dict]) -> None:
        super().__init__(tools)
        self.block_tools = False
        self.tools_entered = asyncio.Event()
        self.release_tools = asyncio.Event()

    async def post(self, url, json, headers):  # noqa: ANN001 - test seam
        if self.block_tools and json.get("method") == "tools/list":
            self.tools_entered.set()
            await self.release_tools.wait()
        return await super().post(url, json, headers)


class _TrackingMcpServer(_FakeMcpServer):
    def __init__(self, endpoint: str, calls: list[dict]) -> None:
        super().__init__(list(_TOOLS))
        self.endpoint = endpoint
        self.calls = calls

    async def post(self, url, json, headers):  # noqa: ANN001 - test seam
        self.calls.append(
            {
                "endpoint": self.endpoint,
                "request_url": url,
                "method": json.get("method"),
                "authorization": headers.get("Authorization"),
            }
        )
        return await super().post(url, json, headers)


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
    await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p1",
    )
    await _approved(
        k,
        "control.mcp_server.activate",
        {"server_id": "ext-mcp"},
        run_id="a1",
    )
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

    out = await _approved(
        k,
        "control.mcp_server.deactivate",
        {"server_id": "ext-mcp"},
        run_id="d1",
    )
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
    out = await _approved(
        k,
        "control.mcp_server.activate",
        {"server_id": "ext-mcp"},
        run_id="a2",
    )
    assert out["activated"] is True
    out = await k.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r4"))
    assert out == {"text": "done"}


@pytest.mark.invariant("SEC-22")
async def test_deactivate_is_a_clean_noop_on_an_inert_adapter(monkeypatch):
    k = await _kernel()
    await _register(monkeypatch, k, _FakeMcpServer(list(_TOOLS)))
    await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p1",
    )

    with pytest.raises(AdapterFailure) as refused:
        await k.invoke(
            "control",
            "control.mcp_server.deactivate",
            {"server_id": "ext-mcp"},
            _ctx(["*"], run_id="d1"),
        )
    assert refused.value.status_code == 409
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

    with pytest.raises(AdapterFailure) as caught:
        await k.invoke(
            "control", "control.adapter.delete", {"adapter_id": "ext-mcp"}, _ctx(["*"])
        )
    assert caught.value.status_code == 409
    assert "dedicated lifecycle" in str(caught.value)
    # nothing was torn down: the adapter is still live and dispatchable
    record = await k.store.get_adapter(T, "ext-mcp")
    assert record is not None and record.activated is True
    out = await k.invoke("ext-mcp", "ext-mcp.ticket.read", {"id": "1"}, _ctx(["*"], run_id="r1"))
    assert out == {"text": "done"}


@pytest.mark.invariant("SEC-22")
async def test_retire_preserves_registration_and_history(monkeypatch):
    k = await _kernel()
    store = k.store
    await _live(monkeypatch, k)
    assert (await store.get_credential_ref(T, "ext-mcp-mcp-token")) is not None
    assert (await k.credentials.resolve_for_adapter(T, "ext-mcp")) is not None
    await _approved(
        k,
        "control.mcp_server.deactivate",
        {"server_id": "ext-mcp"},
        run_id="d1",
    )
    out = await _approved(
        k,
        "control.mcp_server.retire",
        {"server_id": "ext-mcp"},
        run_id="x1",
    )
    assert out["state"] == "retired"
    assert await store.get_adapter(T, "ext-mcp") is not None
    assert await store.get_verb(T, "ext-mcp.ticket.read") is None
    assert await store.get_binding(T, "ext-mcp.ticket.read") is None
    assert await store.get_noun(T, "ext-mcp") is None  # orphaned by the removal
    assert await store.get_credential_ref(T, "ext-mcp-mcp-token") is not None
    assert await k.credentials.resolve_for_adapter(T, "ext-mcp") is not None
    assert k.loader.peek(T, "ext-mcp") is not None


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
        "credential_id": "ext-mcp-mcp-token",
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
        "credential_id": None,
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
    await k.store.set_mcp_server_lifecycle(
        T,
        "legacy-mcp",
        expected_state=None,
        expected_config_revision=None,
        new_state="inactive",
        changed_at=utcnow(),
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
    await store.upsert_adapter(
        AdapterRecord(
            id="gen-tampered",
            tenant_id=T,
            version="1",
            runtime="http",
            source="generated",
            module_ref="boltrig.adapters.generator",
            spec_ref=(
                '{"kind":"boltrig.generated-openapi.v1",'
                '"operations":[]}'
            ),
        )
    )
    # A legacy generated row created before durable projections has no honest
    # reconstruction source and must still be skipped.
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
    assert k.loader.peek(T, "gen-tampered") is None
    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("url-less" in message and "spec_ref" in message for message in warnings)
    assert any("gen-1" in message for message in warnings)
    assert any("gen-tampered" in message for message in warnings)


@pytest.mark.invariant("SEC-22")
async def test_generated_adapter_is_durable_across_restart_and_replicas(
    monkeypatch,
):
    from fastapi.testclient import TestClient

    from boltrig.adapters.base import Result
    from boltrig.adapters.generator import GeneratedAdapter
    from boltrig.api.bootstrap import _rehydrate_store_adapters
    from boltrig.config.control_generated_adapter import GENERATED_ADAPTER_KIND
    from boltrig.kernel.app import create_app

    k1 = await _kernel()
    generated = await k1.invoke(
        "control",
        "control.adapter.generate",
        {"adapter_id": "durable-generated", "spec": _GENERATED_SPEC},
        _ctx(["*"], run_id="generate-durable"),
    )
    assert generated["activated"] is False
    record = await k1.store.get_adapter(T, "durable-generated")
    assert record is not None and record.activated is False
    projection = json.loads(record.spec_ref)
    assert projection["kind"] == GENERATED_ADAPTER_KIND
    assert "unused-openapi-secret-canary" not in record.spec_ref
    assert await k1.store.get_verb(T, "thing.list") is None
    original_source = k1.loader.peek(T, "durable-generated").render_source()

    k2 = await _restart_kernel(k1.store)
    await _rehydrate_store_adapters(k2, T)
    rebuilt = k2.loader.peek(T, "durable-generated")
    assert rebuilt is not None
    assert rebuilt.activated is False
    assert rebuilt.render_source() == original_source
    assert [spec.verb_id for spec in rebuilt.describe()] == ["thing.list"]
    client = TestClient(create_app(k2))
    source = client.get(
        "/v1/adapters/durable-generated/source",
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "author",
            "x-boltrig-role": "org-admin",
        },
    )
    assert source.status_code == 200
    assert source.json()["source"] == original_source
    assert "unused-openapi-secret-canary" not in source.text

    activated = await _approved(
        k2,
        "control.adapter.activate",
        {"adapter_id": "durable-generated"},
        run_id="activate-durable",
    )
    assert activated["activated"] is True
    assert activated["verbs"] == ["thing.list"]
    assert await k2.store.get_binding(T, "thing.list") is not None

    # A third replica reconstructs active authority from the store. Execution
    # still enters through Dispatcher; only the deterministic HTTP seam is
    # replaced so the test performs no network I/O.
    k3 = await _restart_kernel(k2.store)
    await _rehydrate_store_adapters(k3, T)
    active = k3.loader.peek(T, "durable-generated")
    assert active is not None and active.activated is True

    async def execute_without_network(self, verb, params, credential, context):
        return Result.success({"replica": "reconstructed", "verb": verb})

    monkeypatch.setattr(GeneratedAdapter, "execute", execute_without_network)
    assert await k3.invoke(
        "thing",
        "thing.list",
        {},
        _ctx(["*"], run_id="replica-dispatch"),
    ) == {"replica": "reconstructed", "verb": "thing.list"}

    assert (
        await _approved(
            k2,
            "control.adapter.deactivate",
            {"adapter_id": "durable-generated"},
            run_id="deactivate-durable",
        )
    )["activated"] is False
    assert await k3.adapter_provider(T, "durable-generated") is None
    inert = k3.loader.peek(T, "durable-generated")
    assert inert is not None and inert.activated is False
    with pytest.raises(BindingNotFound):
        await k3.invoke(
            "thing",
            "thing.list",
            {},
            _ctx(["*"], run_id="stale-replica-refused"),
        )
    assert "unused-openapi-secret-canary" not in repr(
        await k3.store.audit_query(T, limit=100)
    )


@pytest.mark.invariant("SEC-22")
async def test_lifecycle_verbs_govern_a_store_only_phantom_row(monkeypatch):
    """No rehydration after the restart: deactivate/delete must still govern the
    row via the store fallback in the approval context."""
    k1 = await _kernel()
    await _live(monkeypatch, k1)
    k2 = await _restart_kernel(k1.store)  # restart WITHOUT rehydration
    assert k2.loader.peek(T, "ext-mcp") is None

    out = await _approved(
        k2,
        "control.mcp_server.deactivate",
        {"server_id": "ext-mcp"},
        run_id="pd1",
    )
    assert out["activated"] is False
    assert set(out["verbs"]) == {"ext-mcp.ticket.read", "ext-mcp.ticket.create"}

    out = await _approved(
        k2,
        "control.mcp_server.retire",
        {"server_id": "ext-mcp"},
        run_id="px1",
    )
    assert out["state"] == "retired"

    store = k2.store
    assert await store.get_adapter(T, "ext-mcp") is not None
    assert await store.get_verb(T, "ext-mcp.ticket.read") is None
    assert await store.get_noun(T, "ext-mcp") is None
    assert await store.get_credential_ref(T, "ext-mcp-mcp-token") is not None


# --- approval-gated activation: no silent re-pend, phantom activation --------
@pytest.mark.invariant("SEC-14")
async def test_a_consumed_approval_fails_loudly_instead_of_repending(monkeypatch):
    """The live infinite-pend repro: retry #1 spends the approval and then the
    activation FAILS (here: a verb ownership conflict); retry #2 with the spent
    approval_id previously returned 202 with a FRESH pend forever. A spent
    approval must fail loudly - the caller inspects state, not re-approves."""
    k = await _kernel()
    await _register(monkeypatch, k, _FakeMcpServer(list(_TOOLS)))
    await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p1",
    )
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

    params = {"server_id": "ext-mcp"}
    with pytest.raises(PendingHuman) as held:
        await k.invoke(
            "control",
            "control.mcp_server.activate",
            params,
            _ctx(["*"], run_id="a1"),
        )
    req_id = held.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    with pytest.raises(AdapterFailure) as conflict:
        await k.invoke(
            "control", "control.mcp_server.activate", params,
            _ctx(["*"], run_id="a1"), approval_id=req_id,
        )
    assert conflict.value.status_code == 409  # activation refused; approval spent

    with pytest.raises(HITLStateConflict) as spent:
        await k.invoke(
            "control", "control.mcp_server.activate", params,
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

    await _approved(
        k2,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p1",
    )
    out = await _approved(
        k2,
        "control.mcp_server.activate",
        {"server_id": "ext-mcp"},
        run_id="a1",
    )

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
    await k.store.set_mcp_server_lifecycle(
        T,
        "old-mcp",
        expected_state=None,
        expected_config_revision=None,
        new_state="inactive",
        changed_at=utcnow(),
    )

    with pytest.raises(AdapterFailure) as caught:
        await k.invoke(
            "control",
            "control.mcp_server.probe",
            {"server_id": "old-mcp"},
            _ctx(["*"]),
        )

    assert caught.value.status_code == 409
    assert caught.value.reason == "endpoint_not_configured"
    assert await k.hitl.list_pending(T) == []
    # Retiring is still available without probing and preserves the audit row.
    out = await _approved(
        k,
        "control.mcp_server.retire",
        {"server_id": "old-mcp"},
        run_id="x1",
    )
    assert out["state"] == "retired"
    assert await k.store.get_adapter(T, "old-mcp") is not None


@pytest.mark.invariant("SEC-22")
async def test_concurrent_mcp_activation_loser_preserves_the_winner(monkeypatch):
    """A losing activation CAS must not unpublish or deactivate its winner."""
    from boltrig.config.control_mcp_lifecycle import _activate
    from boltrig.config.control_safety import ControlConflict

    k = await _kernel()
    await _register(monkeypatch, k, _FakeMcpServer(list(_TOOLS)))
    await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p1",
    )
    record = await k.store.get_adapter(T, "ext-mcp")
    lifecycle = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert record is not None and lifecycle is not None

    class RacingRegistry:
        def __init__(self):
            self.arrived = 0
            self.both_arrived = asyncio.Event()

        async def register_adapter_verbs(self, tenant_id, adapter):
            registered = await k.registry.register_adapter_verbs(tenant_id, adapter)
            self.arrived += 1
            if self.arrived == 2:
                self.both_arrived.set()
            await self.both_arrived.wait()
            return registered

    context = _ctx(["*"], run_id="race")
    context.extra["approved_by"] = "reviewer"
    racing_registry = RacingRegistry()
    results = await asyncio.gather(
        _activate(
            k.store,
            k.loader,
            racing_registry,
            k.credentials,
            context,
            record,
            lifecycle,
        ),
        _activate(
            k.store,
            k.loader,
            racing_registry,
            k.credentials,
            context,
            record,
            lifecycle,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ControlConflict) for result in results) == 1
    final = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert final is not None and final.state == "active"
    assert await k.store.get_verb(T, "ext-mcp.ticket.read") is not None
    assert k.loader.peek(T, "ext-mcp").activated is True


async def _direct_mcp_update(
    k: Kernel,
    *,
    params: dict,
    run_id: str,
):
    from boltrig.config.control_approval_adapters import mcp_server_context
    from boltrig.config.control_mcp_mutations import (
        execute_mcp_registration_mutation,
    )

    context = _ctx(["*"], run_id=run_id)
    context.extra["approval_resource_context"] = await mcp_server_context(
        k.store,
        "control.mcp_server.update",
        params,
        context,
    )
    record = await k.store.get_adapter(T, str(params["server_id"]))
    assert record is not None
    return await execute_mcp_registration_mutation(
        k.store,
        k.loader,
        k.credentials,
        "control.mcp_server.update",
        params,
        context,
        record,
    )


@pytest.mark.invariant("SEC-WRK-21")
async def test_mcp_probe_update_race_discards_stale_remote_result(
    monkeypatch,
):
    """An old-generation probe may finish, but cannot write any evidence."""
    from boltrig.config.control_mcp_lifecycle import _probe_once
    from boltrig.config.control_safety import ControlConflict

    k = await _kernel()
    server = _BlockingMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)
    record = await k.store.get_adapter(T, "ext-mcp")
    lifecycle = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert record is not None and lifecycle is not None
    update = {
        "server_id": "ext-mcp",
        "url": "https://new-mcp.example.com/v2",
        "allow_internal": False,
        "credential_mode": "preserve",
    }
    server.block_tools = True
    stale_probe = asyncio.create_task(
        _probe_once(
            k.store,
            k.loader,
            k.credentials,
            T,
            record,
            expected_config_revision=lifecycle.config_revision,
        )
    )
    await server.tools_entered.wait()
    try:
        amended = await _direct_mcp_update(k, params=update, run_id="u-race")
    finally:
        server.release_tools.set()
    assert amended.ok is True
    with pytest.raises(ControlConflict, match="changed during probe"):
        await stale_probe
    current = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert current is not None
    assert current.config_revision == 2
    assert current.last_known_tools == ()
    assert current.tools_observed_at is None
    assert await k.store.list_mcp_probe_receipts(T, "ext-mcp") == []


@pytest.mark.invariant("SEC-WRK-21")
async def test_mcp_activation_update_race_publishes_no_stale_authority(
    monkeypatch,
):
    """Config replacement wins while activation probes; old tools stay inert."""
    from boltrig.config.control_mcp_lifecycle import _activate
    from boltrig.config.control_safety import ControlConflict

    k = await _kernel()
    server = _BlockingMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)
    await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p-race",
    )
    record = await k.store.get_adapter(T, "ext-mcp")
    lifecycle = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert record is not None and lifecycle is not None
    activation_context = _ctx(["*"], run_id="a-race")
    activation_context.extra["approved_by"] = "reviewer"
    update = {
        "server_id": "ext-mcp",
        "url": "https://new-mcp.example.com/v2",
        "allow_internal": False,
        "credential_mode": "preserve",
    }
    server.block_tools = True
    activation = asyncio.create_task(
        _activate(
            k.store,
            k.loader,
            k.registry,
            k.credentials,
            activation_context,
            record,
            lifecycle,
            expected_config_revision=lifecycle.config_revision,
        )
    )
    await server.tools_entered.wait()
    try:
        amended = await _direct_mcp_update(k, params=update, run_id="u2-race")
    finally:
        server.release_tools.set()
    assert amended.ok is True
    with pytest.raises(ControlConflict, match="changed during probe"):
        await activation
    current = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert current is not None
    assert current.state == "inactive"
    assert current.config_revision == 2
    assert current.last_known_tools == ()
    assert await k.store.get_verb(T, "ext-mcp.ticket.read") is None
    assert k.loader.peek(T, "ext-mcp").activated is False


@pytest.mark.invariant("SEC-WRK-21")
async def test_cross_replica_mcp_dispatch_reconciles_endpoint_and_credential(
    monkeypatch,
):
    """A stale replica dispatches only against the current durable generation."""
    from boltrig.config.control_rehydrate import rehydrate_adapter_instance

    monkeypatch.setenv("OLD_MCP_REF", "old-bearer")
    monkeypatch.setenv("NEW_MCP_REF", "new-bearer")
    calls: list[dict] = []

    def client_for(url, *args, **kwargs):  # noqa: ANN001 - pinned client seam
        return _TrackingMcpServer(url, calls)

    monkeypatch.setattr(
        "boltrig.adapters.egress.pinned_async_client",
        client_for,
    )
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    primary = Kernel(store)
    stale = Kernel(store)
    for kernel in (primary, stale):
        await kernel.register_adapter(
            T,
            build_control_plane_adapter(
                store,
                loader=kernel.loader,
                registry=kernel.registry,
                credentials=kernel.credentials,
            ),
        )
    await primary.invoke(
        "control",
        "control.mcp_server.register",
        {
            "id": "ext-mcp",
            "url": "https://old-mcp.example.com/v1",
            "credential_ref": "OLD_MCP_REF",
        },
        _ctx(["*"], run_id="register-old"),
    )
    old_record = await store.get_adapter(T, "ext-mcp")
    assert old_record is not None
    old_live = await rehydrate_adapter_instance(
        store,
        stale.credentials,
        stale.loader,
        T,
        old_record,
    )
    assert old_live is not None
    assert old_live._url == "https://old-mcp.example.com/v1"

    updated = await _approved(
        primary,
        "control.mcp_server.update",
        {
            "server_id": "ext-mcp",
            "url": "https://new-mcp.example.com/v2/private",
            "allow_internal": False,
            "credential_mode": "replace",
            "credential_ref": "NEW_MCP_REF",
        },
        run_id="replace-config",
    )
    assert updated["config_revision"] == 2
    await _approved(
        primary,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="probe-new",
    )
    await _approved(
        primary,
        "control.mcp_server.activate",
        {"server_id": "ext-mcp"},
        run_id="activate-new",
    )

    calls.clear()
    output = await stale.invoke(
        "ext-mcp",
        "ext-mcp.ticket.read",
        {"id": "ticket-1"},
        _ctx(["*"], run_id="stale-replica-dispatch"),
    )
    assert output == {"text": "done"}
    assert calls
    assert {call["endpoint"] for call in calls} == {
        "https://new-mcp.example.com/v2/private"
    }
    assert {call["request_url"] for call in calls} == {
        "https://new-mcp.example.com/v2/private"
    }
    assert {call["authorization"] for call in calls} == {
        "Bearer new-bearer"
    }

    # Even if another replica leaves published bindings and a live instance
    # behind, durable inactive state is authoritative before any external I/O.
    lifecycle = await store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert lifecycle is not None
    assert (
        await store.set_mcp_server_lifecycle(
            T,
            "ext-mcp",
            expected_state="active",
            expected_config_revision=lifecycle.config_revision,
            new_state="inactive",
            changed_at=utcnow(),
        )
        is not None
    )
    assert await store.get_binding(T, "ext-mcp.ticket.read") is not None
    assert stale.loader.peek(T, "ext-mcp") is not None
    calls.clear()
    assert await stale.adapter_provider(T, "ext-mcp") is None
    assert calls == []
    inert = stale.loader.peek(T, "ext-mcp")
    assert inert is not None and inert.activated is False


@pytest.mark.invariant("SEC-WRK-21")
async def test_authoritative_provider_preserves_non_mcp_dispatch() -> None:
    from boltrig.adapters.base import Result, VerbSpec

    class OrdinaryAdapter:
        id = "ordinary"
        version = "1"
        runtime = "script"
        source = "builtin"
        activated = True

        def describe(self):
            return [
                VerbSpec(
                    verb_id="ordinary.echo",
                    noun_id="ordinary",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            ]

        async def execute(self, verb, params, credential, context):
            return Result.success({"echo": params["value"]})

        async def health(self):
            return "ok"

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    adapter = OrdinaryAdapter()
    await kernel.register_adapter(T, adapter)
    assert await kernel.adapter_provider(T, "ordinary") is adapter
    assert await kernel.invoke(
        "ordinary",
        "ordinary.echo",
        {"value": "still-routed"},
        _ctx(["*"], run_id="ordinary-provider"),
    ) == {"echo": "still-routed"}


async def test_oversize_stored_snapshot_degrades_one_adapter_not_the_whole_kernel(
    monkeypatch,
):
    """A stored snapshot the validator rejects must not refuse the process a start.

    Regression, measured on the beelink 2026-07-30. `d072c92` added
    MCP_MAX_TOOL_SNAPSHOT=500 and validated it inside ``apply_tool_snapshot``, which
    rehydrate calls at boot. The live `opbox` consumer publishes 633 verbs, so the
    kernel died on EVERY start with "MCP tool snapshot is out of bounds" the moment
    the image was rebuilt. Raising here cannot stop bad data arriving - the snapshot
    is already stored - it can only turn one unusable adapter into a dead kernel.
    """
    from boltrig.config import control_rehydrate
    from boltrig.config.control_rehydrate import rehydrate_adapter_instance

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store,
            loader=kernel.loader,
            registry=kernel.registry,
            credentials=kernel.credentials,
        ),
    )
    monkeypatch.setenv("SOME_MCP_REF", "a-bearer")
    await kernel.invoke(
        "control",
        "control.mcp_server.register",
        {
            "id": "ext-mcp",
            "url": "https://mcp.example.com/v1",
            "credential_ref": "SOME_MCP_REF",
        },
        _ctx(["*"], run_id="register-oversize"),
    )
    record = await store.get_adapter(T, "ext-mcp")
    assert record is not None

    # Red-seed: without the try/except this propagates and startup dies.
    def _reject(snapshot):  # noqa: ANN001 - test seam
        raise ValueError("MCP tool snapshot is out of bounds")

    monkeypatch.setattr(
        "boltrig.adapters.mcp_consumer.validate_mcp_tool_snapshot", _reject
    )

    live = await rehydrate_adapter_instance(
        store, kernel.credentials, kernel.loader, T, record
    )
    assert live is None, "the adapter must be skipped, not raised through"
    assert control_rehydrate.log is not None


def test_snapshot_cap_admits_a_real_registry():
    """The cap must sit ABOVE a shipping adapter, not below it.

    `opbox` published 633 verbs on 2026-07-30 against a cap of 500. A ceiling that a
    real deployment exceeds is not a safety bound, it is an outage. The payload bound
    that does the actual work is MCP_MAX_TOOL_SNAPSHOT_BYTES.
    """
    from boltrig.models.mcp_lifecycle import MCP_MAX_TOOL_SNAPSHOT

    assert MCP_MAX_TOOL_SNAPSHOT > 633
