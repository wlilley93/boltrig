"""The kernel MCP server face (Epic MCP): granted-only tools + chokepoint parity.

Every tools/call runs the unchanged dispatch order, so grants, the HITL gate, and
audit apply identically to a direct invoke (SEC-26). A run-scoped token exposes
only that run's tools (SEC-23, FR-MCP-02).
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel(blocking=None) -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store, blocking_verbs=blocking or set())
    await k.register_adapter(T, build_tickets())
    return k


def _req(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-01")
async def test_tools_list_is_granted_only_with_schemas():
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    res = await k.mcp.handle(tok, _req("tools/list"))
    tools = {t["name"]: t for t in res["result"]["tools"]}
    assert set(tools) == {"ticket.read"}  # ticket.create is out of this run's grants
    assert "id" in tools["ticket.read"]["inputSchema"]["properties"]  # schema advertised


@pytest.mark.security
@pytest.mark.invariant("SEC-26")
async def test_tools_call_runs_chokepoint_and_audits():
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.create"]), run_id="r1", actor="pi-run")
    res = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert res["result"]["isError"] is False
    assert res["result"]["_boltrig"]["output"]["status"] == "open"
    events = await k.store.audit_query(T)
    assert events[-1].verb == "ticket.create" and events[-1].actor == "pi-run"


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-02")
@pytest.mark.invariant("SEC-23")
async def test_out_of_scope_verb_not_listed_and_denied():
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))  # cannot create
    listed = {t["name"] for t in (await k.mcp.handle(tok, _req("tools/list")))["result"]["tools"]}
    assert "ticket.create" not in listed
    # defence in depth: calling it anyway is denied at the chokepoint
    call = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert call["result"]["isError"] is True
    assert call["result"]["_boltrig"]["status"] == "denied"


@pytest.mark.security
@pytest.mark.invariant("SEC-26")
async def test_mcp_hitl_gate_parity():
    k = await _kernel(blocking={"ticket.create"})
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.create"]))
    res = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert res["result"]["_boltrig"]["status"] == "pending_human"
    assert res["result"]["_boltrig"]["hitl_request_id"]


@pytest.mark.security
async def test_invalid_token_rejected():
    k = await _kernel()
    res = await k.mcp.handle("not-a-token", _req("tools/list"))
    assert "error" in res


@pytest.mark.security
@pytest.mark.invariant("SEC-149")
async def test_run_tokens_are_hashed_expiring_and_immediately_revocable():
    k = await _kernel()
    clock = [datetime(2026, 7, 15, tzinfo=timezone.utc)]
    k.mcp._clock = lambda: clock[0]
    token = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]), ttl_seconds=2)

    assert token not in k.mcp._tokens
    assert token not in repr(k.mcp._tokens)
    assert k.mcp.is_run_token(token)

    clock[0] += timedelta(seconds=2)
    expired = await k.mcp.handle(token, _req("tools/list"))
    assert expired["error"]["message"] == "invalid or expired run token"
    assert not k.mcp.is_run_token(token)

    replacement = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    k.mcp.revoke(replacement)
    assert not k.mcp.is_run_token(replacement)

    with pytest.raises(ValueError, match="TTL"):
        k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]), ttl_seconds=0)


@pytest.mark.security
def test_mcp_http_route():
    k = asyncio.run(_kernel())
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    client = TestClient(create_app(k))
    r = client.post("/v1/mcp", json=_req("tools/list"), headers={"x-boltrig-mcp-token": tok})
    assert r.status_code == 200
    assert any(t["name"] == "ticket.read" for t in r.json()["result"]["tools"])


@pytest.mark.security
@pytest.mark.invariant("SEC-184")
def test_mcp_notification_gets_202_with_no_body():
    """A JSON-RPC notification is never answered with a response frame.

    Strict streamable-HTTP clients (Codex's rmcp worker) treat a response to
    ``notifications/initialized`` - with a null id - as a fatal transport error
    and kill the whole MCP connection; that was the live codex-lane failure.
    """
    k = asyncio.run(_kernel())
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    client = TestClient(create_app(k))
    note = client.post(
        "/v1/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"x-boltrig-mcp-token": tok},
    )
    assert note.status_code == 202
    assert not note.content
    # A request-shaped message (an id) keeps its 200 JSON-RPC body.
    ping = client.post(
        "/v1/mcp", json=_req("ping"), headers={"x-boltrig-mcp-token": tok}
    )
    assert ping.status_code == 200
    assert ping.json()["result"] == {}


@pytest.mark.security
async def test_schema_failure_names_the_offending_field_for_a_granted_caller():
    """A schema rejection must say what was wrong, or the model cannot self-correct.

    The live defect this closes: on the Classical Visas tenant the model called
    ``opbox.get_matter`` with ``{"number": ...}`` NINE consecutive times, each
    answered with the single word ``schema_invalid``, and only then degenerated
    into emitting tool calls as prose. The verb it wanted, ``get_matter_by_number``,
    was offered to it in the same request. It was never told which key was wrong.

    Names only, never values: the schema is third-party data for an MCP-imported
    verb (``const``/``enum`` put literals in it), so this reports the KEYS and not
    what they must contain. That is the same names-versus-values cut the
    schema-validation ledger order draws for the append-only store.
    """
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.create"]))
    res = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"titel": "x"}})
    )
    r = res["result"]
    text = r["content"][0]["text"]
    assert r["isError"] is True
    # The machine-readable reason is UNCHANGED; only the human/model-facing text grows.
    assert r["_boltrig"]["reason"] == "schema_invalid"
    assert "title" in text, f"the required key was not named: {text!r}"
    assert "titel" in text, f"the key actually sent was not named: {text!r}"


@pytest.mark.security
@pytest.mark.invariant("SEC-23")
async def test_schema_failure_tells_an_ungranted_caller_nothing_about_the_schema():
    """The gate, not the absence of values: disclosure requires authorisation.

    ``dispatch.py`` validates params (:520) BEFORE it checks grants (:524), so a
    caller with no grant on a verb still reaches the schema rejection. Without a
    gate, the richer message above would hand that caller the input-schema shape
    of every verb in the tenant - exactly what ``_list_tools`` exists to withhold.
    """
    k = await _kernel()
    # Granted ticket.read only; ticket.create is outside this run's grants.
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    res = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"titel": "x"}})
    )
    text = res["result"]["content"][0]["text"]
    assert res["result"]["isError"] is True
    assert "title" not in text, f"leaked a schema property to an ungranted caller: {text!r}"
    assert text == "schema_invalid", f"expected the bare reason, got {text!r}"


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-03")
async def test_a_run_scoped_token_cannot_exceed_its_grants_at_the_chokepoint():
    """A run token issued for one verb cannot call another (FR-RUN-03).

    This case arrived here from ``tests/security/test_pi_runtime.py``, deleted with
    the Pi lane ([2026] VJS-PC 20 L1). It was filed under Pi and named for Pi, but it
    never exercised PiRuntime: it issues a run-scoped token and asserts the kernel
    refuses an out-of-scope verb. The property belongs to the MCP face and is live for
    every runtime that holds a run token, so it moves rather than dying with its
    former filing. The actor name is the only thing that was ever Pi-specific.
    """
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    token = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]), run_id="r1", actor="worker")
    res = await k.mcp.handle(
        token,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ticket.create", "arguments": {"title": "x"}}},
    )
    assert res["result"]["_boltrig"]["status"] == "denied"


@pytest.mark.security
@pytest.mark.invariant("SEC-26")
async def test_the_ranked_offer_changes_the_order_but_never_the_authority():
    """[2026] VJS-CC-VJS 10 D3: disclosure only ever REDUCES what a model sees.

    The order was wired precisely because an unwired ranker decides nothing. So the
    thing that must be proven is not that ranking happens, but that ranking cannot
    reach authority: whatever the offer says, the chokepoint answers the same.

    Seeded both ways. If ``_list_tools`` ever gained the power to widen, the first
    assertion goes red; if it ever narrowed authority instead of context, the second
    does.
    """
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    offered = {t["name"] for t in (await k.mcp.handle(tok, _req("tools/list")))["result"]["tools"]}

    # 1. The offer never exceeds the grants: an ungranted verb is not published...
    assert "ticket.create" not in offered

    # ...and is still REFUSED at the chokepoint, which is the check that matters.
    denied = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert denied["result"]["_boltrig"]["status"] == "denied"

    # 2. A verb the grants DO admit is NOT denied, whatever the offer did with it.
    # This is the limb that catches a ranker that quietly dropped rather than sorted.
    # It asserts "not denied" rather than "ok" on purpose: whether this adapter can
    # serve the read is not this test's subject, and asserting success here would
    # make it fail for a reason that has nothing to do with disclosure.
    ok = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.read", "arguments": {"id": "1"}})
    )
    assert ok["result"]["_boltrig"]["status"] != "denied"


@pytest.mark.security
async def test_the_wired_offer_is_stable_and_drops_nothing_granted():
    """CC-VJS 10 D2 at the WIRING level: repeated identical runs give the identical
    offer, and ranking never loses a granted verb.

    Deliberately NOT claiming to prove the total order. Seeding a removal of the
    verb-id tie-break leaves this green, because the input arrives in one order and
    the sort is stable, and it is
    ``tests/unit/test_tool_disclosure.py::test_the_order_is_total_and_independent_of_the_order_the_verbs_arrived_in``
    that goes red for that defect. Saying so here rather than letting the name imply
    a guarantee this does not give is the CC-VJS 11 rule applied to a test."""
    k = await _kernel()
    grants = GrantSet.of(["ticket.read", "ticket.create"])
    first = [t["name"] for t in (await k.mcp.handle(k.mcp.issue_run_token(T, grants), _req("tools/list")))["result"]["tools"]]
    for _ in range(5):
        again = [t["name"] for t in (await k.mcp.handle(k.mcp.issue_run_token(T, grants), _req("tools/list")))["result"]["tools"]]
        assert again == first, "the offer must not vary between identical runs"
    assert len(first) == 2, "ranking must not drop a granted verb"
