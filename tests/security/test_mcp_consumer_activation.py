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

import json

import httpx
import pytest

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.models import (
    AdapterFailure,
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
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
        # a positive low signal reads low; ABSENCE of any hint now fails
        # closed high (owner-approved 2026-08-16)
    },
    {
        "name": "ticket.purge",
        "description": "purge tickets",
        "inputSchema": {"type": "object"},
        "consequence": "critical",  # outside the vocabulary: fails closed high
    },
]


class _FakeMcpServer:
    """Stands in for the external MCP server at the pinned-HTTP seam: records the
    bearer each POST sent and answers the MCP methods a consumer issues.

    It speaks the PLAIN convention (plain JSON 200 answers, no session), so the
    consumer's lazy handshake never fires here; the strict Streamable-HTTP door
    is exercised in tests/adapters/test_mcp_consumer_adapter.py.

    It answers a real ``httpx.MockTransport`` rather than hand-implementing
    httpx's surface. The hand-rolled version could only express
    ``post(url, json, headers)``, and the transport now reads its body through
    ``bounded_http_response``, which streams via ``build_request``/``send`` - a
    bound a fake with only ``post`` cannot exercise at all.
    """

    def __init__(self, tools: list[dict]) -> None:
        self.tools = tools
        self.bearers: list[str | None] = []
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.bearers.append(request.headers.get("x-boltrig-mcp-token"))
        body = json.loads(request.content)
        if body.get("method") == "tools/list":
            return httpx.Response(200, json={"result": {"tools": self.tools}})
        return httpx.Response(
            200, json={"result": {"content": [{"type": "text", "text": "done"}]}}
        )

    def build_request(self, *args, **kwargs):
        return self._client.build_request(*args, **kwargs)

    async def send(self, *args, **kwargs):
        return await self._client.send(*args, **kwargs)

    async def post(self, *args, **kwargs):
        return await self._client.post(*args, **kwargs)

    async def __aenter__(self) -> "_FakeMcpServer":
        return self

    async def __aexit__(self, *exc) -> bool:
        # Deliberately does not close: the pinned_client seam hands back this
        # same server for every call, and a MockTransport holds no socket.
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
    return await k.invoke("control", verb, params, _ctx(["*"], run_id=run_id), approval_id=req_id)


async def _register(monkeypatch, k: Kernel, server: _FakeMcpServer) -> None:
    monkeypatch.setenv("MCP_TOK", "server-bearer")
    monkeypatch.setattr("boltrig.adapters.egress.pinned_async_client", lambda url, timeout: server)
    out = await k.invoke(
        "control",
        "control.mcp_server.register",
        {"id": "ext-mcp", "url": "https://mcp.example.com", "credential_ref": "MCP_TOK"},
        _ctx(["*"]),
    )
    assert out["id"] == "ext-mcp" and out["activated"] is False


async def _activate(k: Kernel, *, run_id: str) -> dict:
    lifecycle = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    if lifecycle.tools_observed_at is None:
        await _approved(
            k,
            "control.mcp_server.probe",
            {"server_id": "ext-mcp"},
            run_id=f"{run_id}-probe",
        )
    return await _approved(
        k,
        "control.mcp_server.activate",
        {"server_id": "ext-mcp"},
        run_id=run_id,
    )


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
@pytest.mark.invariant("SEC-199")
async def test_activation_discovers_and_publishes_the_servers_tools(monkeypatch):
    k = await _kernel()
    server = _FakeMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)

    out = await _activate(k, run_id="a1")

    assert out["activated"] is True
    # tools publish NAMESPACED under the adapter id (many apps share one kernel)
    assert set(out["verbs"]) == {
        "ext-mcp.ticket.create",
        "ext-mcp.ticket.read",
        "ext-mcp.ticket.purge",
    }
    # discovery carried the credential the KERNEL resolved, like a dispatch call
    assert server.bearers == ["server-bearer", "server-bearer"]
    consumer = await k.loader.get(T, "ext-mcp")
    assert consumer is not None and consumer.activated is True

    create = await k.store.get_verb(T, "ext-mcp.ticket.create")
    assert create is not None
    assert create.noun_id == "ext-mcp"  # one noun per consumed server
    assert create.input_schema == _TOOLS[0]["inputSchema"]  # schema from tools/list
    assert create.consequence.value == "high"  # the server's declared hint
    read = await k.store.get_verb(T, "ext-mcp.ticket.read")
    assert read is not None and read.consequence.value == "low"  # no hint: default
    purge = await k.store.get_verb(T, "ext-mcp.ticket.purge")
    assert purge is not None and purge.consequence.value == "high"  # unknown fails closed
    assert "data, not instructions" in create.description
    assert _TOOLS[0]["description"] in create.description

    binding = await k.store.get_binding(T, "ext-mcp.ticket.create")
    assert binding is not None
    assert binding.target_type is TargetType.ADAPTER and binding.target_ref == "ext-mcp"


@pytest.mark.invariant("FR-MCP-03")
@pytest.mark.invariant("SEC-22")
async def test_approval_for_the_inert_adapter_covers_discovery(monkeypatch):
    """A catalogue change after approval is retained but never published."""
    k = await _kernel()
    server = _FakeMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)
    await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p1",
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
    # the server grows a tool while the approval waits for a human
    server.tools.append(
        {"name": "ticket.close", "description": "close a ticket", "inputSchema": {}}
    )
    await k.hitl.answer(T, req_id, "approve", "admin@acme")
    with pytest.raises(AdapterFailure):
        await k.invoke(
            "control",
            "control.mcp_server.activate",
            params,
            _ctx(["*"], run_id="a1"),
            approval_id=req_id,
        )
    assert await k.store.get_verb(T, "ext-mcp.ticket.close") is None
    out = await _activate(k, run_id="a2")
    assert "ext-mcp.ticket.close" in out["verbs"]


def _opbox_tool(name: str, risk_class: str) -> dict:
    """A tool descriptor in the EXACT shape the Opbox kernel's tools/list
    projection emits (opbox-kernel kernel/src/mcp/tools.rs ``verb_to_tool``):
    only name/description/inputSchema, the risk class inside the description's
    metadata run (the labels are ``RiskClass::as_str``)."""
    return {
        "name": name,
        "description": (
            f"Opbox verb '{name}' (capability=cap, riskClass={risk_class}, "
            "authz=OrgMember, idempotent=false, egress=None, tier=Core). "
            "Routed through the one kernel dispatch; authz + audit + egress "
            "are enforced at the verb."
        ),
        "inputSchema": {"type": "object", "additionalProperties": True},
    }


@pytest.mark.invariant("FR-MCP-03")
@pytest.mark.invariant("SEC-22")
@pytest.mark.usefixtures("opbox_addon")
async def test_opbox_risk_class_drives_consequence_on_the_published_verbs(monkeypatch, caplog):
    """The Opbox door declares no ``consequence`` hint; its risk class rides in
    the description. Every class above READ must publish high so the HITL gate
    bites. Two live findings are covered too: a tool named like a RESERVED core
    prefix (``system.health``) publishes safely under the namespace, and the
    ``opbox/expand_tools`` presentation meta-tool (a slash, not a verb id) is
    SKIPPED with a warning rather than published."""
    import logging

    k = await _kernel()
    server = _FakeMcpServer(
        [
            _opbox_tool("matter.list", "READ"),
            _opbox_tool("doc.edit", "WRITE"),
            _opbox_tool("d6.token.mint", "SENSITIVE"),
            _opbox_tool("bill.charge", "MONEY"),
            _opbox_tool("client.archive", "DESTRUCTIVE"),
            # live: the Opbox Core catalogue names a tool system.health, which
            # verbatim would hit _RESERVED_VERB_PREFIXES and fail activation
            _opbox_tool("system.health", "READ"),
            {
                # the expand_tools meta-tool's real description: prose, no token
                "name": "opbox/expand_tools",
                "description": "Expand the MCP tool catalog to include more verb "
                "tiers. Call with tier=2 for OnDemand verbs or "
                "tier=3 for Verticals.",
                "inputSchema": {"type": "object"},
            },
        ]
    )
    await _register(monkeypatch, k, server)

    with caplog.at_level(logging.WARNING, logger="boltrig.adapters.mcp_consumer"):
        out = await _activate(k, run_id="a1")

    assert out["activated"] is True
    for verb, expected in {
        "ext-mcp.matter.list": "low",
        "ext-mcp.doc.edit": "high",
        "ext-mcp.d6.token.mint": "high",
        "ext-mcp.bill.charge": "high",
        "ext-mcp.client.archive": "high",
        "ext-mcp.system.health": "low",  # namespaced: no reserved-prefix collision
    }.items():
        row = await k.store.get_verb(T, verb)
        assert row is not None, verb
        assert row.consequence.value == expected, verb
    # the presentation meta-tool is skipped, not published
    assert "ext-mcp.opbox/expand_tools" not in out["verbs"]
    assert await k.store.get_verb(T, "ext-mcp.opbox/expand_tools") is None
    assert any("skipped" in r.message for r in caplog.records if r.levelno >= logging.WARNING)


@pytest.mark.invariant("FR-MCP-03")
async def test_a_second_activation_resyncs_idempotently(monkeypatch):
    k = await _kernel()
    server = _FakeMcpServer(list(_TOOLS))
    await _register(monkeypatch, k, server)
    await _activate(k, run_id="a1")
    before = {v.id for v in await k.store.list_verbs(T)}

    # A probe records a changed catalogue but never hot-publishes new authority.
    server.tools.append(
        {"name": "ticket.close", "description": "close a ticket", "inputSchema": {}}
    )
    out = await _approved(
        k,
        "control.mcp_server.probe",
        {"server_id": "ext-mcp"},
        run_id="p2",
    )
    assert out["probe"]["outcome"] == "succeeded"
    assert await k.store.get_verb(T, "ext-mcp.ticket.close") is None
    after = {v.id for v in await k.store.list_verbs(T)}
    assert after == before
    create = await k.store.get_verb(T, "ext-mcp.ticket.create")
    assert create is not None and create.input_schema == _TOOLS[0]["inputSchema"]
    lifecycle = await k.store.get_mcp_server_lifecycle(T, "ext-mcp")
    assert any(tool.name == "ticket.close" for tool in lifecycle.last_known_tools)


# --- SEC-61: the internal-egress waiver, attacked rather than used -----------
@pytest.mark.security
@pytest.mark.invariant("SEC-61")
async def test_an_internal_targeted_server_cannot_be_called_before_a_human_approves(
    monkeypatch,
):
    """SEC-61's strongest sentence, bound at last.

    `mcp_transport.py` says allow_internal "must never be set for an
    agent-influenced URL", and `control_specs.py` justifies the waiver by saying
    registration is inert until the SEC-22 review gate so "the flag is always
    human-approved before any call". Three tests were bound to SEC-61 and all
    three USED the waiver - none asserted the sentence. `control.mcp_server.
    register` is consequence=low, so an agent holding that grant CAN register an
    internal-targeted server; the whole protection is that it cannot be CALLED.
    So that is what this attacks.
    """
    k = await _kernel()
    monkeypatch.setenv("MCP_TOK", "server-bearer")
    out = await k.invoke(
        "control",
        "control.mcp_server.register",
        {
            "id": "imds-mcp",
            "url": "http://169.254.169.254/mcp",
            "credential_ref": "MCP_TOK",
            "allow_internal": True,
        },
        _ctx(["*"]),
    )
    assert out["activated"] is False, "an internal target must land INERT"

    # The verbs are not published, so there is nothing to dispatch: the server
    # cannot be reached at all while it is unapproved.
    assert [v for v in await k.store.list_verbs(T) if v.id.startswith("imds")] == []


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
async def test_the_approver_is_shown_the_internal_egress_waiver(monkeypatch):
    """The reviewer must be able to SEE what they are approving.

    `control.adapter.activate` takes only {adapter_id}, so the approval payload
    is an id. The resource fingerprint beside it carried
    id/version/runtime/source/activated/verbs and NOT the url or the flag - so
    the human whose approval the waiver rests on was never told the adapter would
    be permitted to reach a link-local address. Because this dict is also the
    unchanged-approval fingerprint, carrying the url and flag means an approval
    given for one target cannot be spent on another.
    """
    from boltrig.config.control_approval import _store_adapter_view

    k = await _kernel()
    monkeypatch.setenv("MCP_TOK", "server-bearer")
    await k.invoke(
        "control",
        "control.mcp_server.register",
        {
            "id": "imds-mcp",
            "url": "http://169.254.169.254/mcp",
            "credential_ref": "MCP_TOK",
            "allow_internal": True,
        },
        _ctx(["*"]),
    )
    record = await k.store.get_adapter(T, "imds-mcp")
    view = await _store_adapter_view(k.store, record, _ctx(["*"]))

    assert view["adapter"]["endpoint_origin"] == "http://169.254.169.254"
    assert view["adapter"]["path_redacted"] is True
    assert view["adapter"]["allow_internal_egress"] is True
    assert len(view["adapter"]["mcp_spec_digest"]) == 64
    assert "169.254.169.254/mcp" not in str(view)
