"""Activation of a consumed MCP server discovers and publishes its tools (US-MCP-03).

The end-to-end demo found the feature wired for registration but not execution:
nothing in production called ``McpConsumerAdapter.connect()``, so activating a
consumed server published ``describe()`` with ZERO verbs, and every consumed
verb would have carried consequence "low" regardless of the server's
declaration. Activation now connects first: tools/list becomes the verb rows
(with the server's input schemas), a declared ``consequence`` hint propagates
(capped at the Consequence enum ceiling, default low), and the discovery call
carries the kernel-resolved credential like any dispatch call.
"""

from __future__ import annotations

import pytest

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantSet,
    InvocationContext,
    PendingHuman,
    TargetType,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"

_TOOLS = [
    {
        "name": "ticket.create",
        "description": "create a ticket",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
        "consequence": "high",  # declared hint: propagates
    },
    {
        "name": "ticket.read",
        "description": "read a ticket",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
        # no hint: defaults to low
    },
    {
        "name": "ticket.purge",
        "description": "purge tickets",
        "inputSchema": {"type": "object"},
        "consequence": "critical",  # above the ceiling: clamps to low
    },
]


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeMcpServer:
    """Stands in for the external MCP server at the pinned-HTTP seam: records the
    bearer each POST sent and answers the MCP methods a consumer issues."""

    def __init__(self, tools: list[dict]) -> None:
        self.tools = tools
        self.bearers: list[str | None] = []

    async def post(self, url, json, headers):  # noqa: ANN001 - httpx-shaped stub
        self.bearers.append(headers.get("x-boltrig-mcp-token"))
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


@pytest.mark.invariant("SEC-167")
async def test_registration_with_credential_ref_binds_the_ref_through_the_chokepoint(
    monkeypatch,
):
    """The documented param now passes the verb schema (it was 400 schema_invalid)
    and binds a REFERENCE on the credential seam - never raw material (SEC-04)."""
    monkeypatch.setenv("MCP_TOK", "secret-material")
    k = await _kernel()
    out = await k.invoke(
        "control",
        "control.mcp_server.register",
        {"id": "ext-mcp", "url": "https://mcp.example.com", "credential_ref": "MCP_TOK"},
        _ctx(["*"]),
    )
    assert out["activated"] is False
    # refs only: the stored record names the secret, it does not contain it
    stored = await k.store.get_credential_ref(T, "ext-mcp-mcp-token")
    assert stored == {"store": "env", "ref": "MCP_TOK", "kind": "api_key"}
    resolved = await k.credentials.resolve_for_adapter(T, "ext-mcp")
    assert resolved is not None and resolved.id == "ext-mcp-mcp-token"


@pytest.mark.invariant("FR-MCP-03")
@pytest.mark.invariant("SEC-22")
async def test_activation_discovers_and_publishes_the_servers_tools(monkeypatch):
    k = await _kernel()
    server = _FakeMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)

    out = await _approved(k, "control.adapter.activate", {"adapter_id": "ext-mcp"}, run_id="a1")

    assert out["activated"] is True
    assert set(out["verbs"]) == {"ticket.create", "ticket.read", "ticket.purge"}
    # discovery carried the credential the KERNEL resolved, like a dispatch call
    assert server.bearers == ["server-bearer"]
    consumer = await k.loader.get(T, "ext-mcp")
    assert consumer is not None and consumer.activated is True

    create = await k.store.get_verb(T, "ticket.create")
    assert create is not None
    assert create.input_schema == _TOOLS[0]["inputSchema"]  # schema from tools/list
    assert create.consequence.value == "high"  # the server's declared hint
    read = await k.store.get_verb(T, "ticket.read")
    assert read is not None and read.consequence.value == "low"  # no hint: default
    purge = await k.store.get_verb(T, "ticket.purge")
    assert purge is not None and purge.consequence.value == "low"  # clamped to the ceiling

    binding = await k.store.get_binding(T, "ticket.create")
    assert binding is not None
    assert binding.target_type is TargetType.ADAPTER and binding.target_ref == "ext-mcp"


@pytest.mark.invariant("FR-MCP-03")
async def test_a_second_activation_resyncs_idempotently(monkeypatch):
    k = await _kernel()
    server = _FakeMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)
    await _approved(k, "control.adapter.activate", {"adapter_id": "ext-mcp"}, run_id="a1")
    before = {v.id for v in await k.store.list_verbs(T)}

    # the server adds a tool; re-activation re-discovers without duplicating rows
    server.tools.append(
        {"name": "ticket.close", "description": "close a ticket", "inputSchema": {}}
    )
    out = await _approved(k, "control.adapter.activate", {"adapter_id": "ext-mcp"}, run_id="a2")

    assert out["activated"] is True
    assert "ticket.close" in out["verbs"]
    after = {v.id for v in await k.store.list_verbs(T)}
    assert after == before | {"ticket.close"}
    # a re-synced verb keeps exactly one row, still bound to the consumer
    create = await k.store.get_verb(T, "ticket.create")
    assert create is not None and create.input_schema == _TOOLS[0]["inputSchema"]
    binding = await k.store.get_binding(T, "ticket.close")
    assert binding is not None and binding.target_ref == "ext-mcp"
