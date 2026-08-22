"""Flat named-peer topology, mailbox durability, and authority boundaries."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from boltrig.adapters.builtin.agent_messages import build as build_agent_messages
from boltrig.config.manifest import (
    FleetManifest,
    NamedAgentConfig,
    NamedAgentsConfig,
)
from boltrig.fleet import AgentMailboxService, build_org, build_spawner
from boltrig.fleet.result import AgentResult
from boltrig.kernel import Kernel
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    AgentDeliveryStatus,
    AgentMessage,
    AgentMessageKind,
    AgentTurnLane,
    AdapterFailure,
    GrantSet,
    InvocationContext,
    NamedAgent,
    SchemaValidationError,
    TenantPermissions,
    context_to_envelope,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _store() -> InMemoryStore:
    store = InMemoryStore()
    for address in ("alice", "bob", "carol"):
        await store.upsert_named_agent(
            NamedAgent(
                tenant_id=T,
                address=address,
                name=address,
                runtime="script",
                default_for_intake=address == "alice",
            )
        )
    return store


def _context(actor: str = "alice", *, tier: str = "tier1", run_id: str = "run-1"):
    return InvocationContext(
        tenant_id=T,
        run_id=run_id,
        grants=GrantSet.of(["agent.send", "ticket.read"]),
        actor=actor,
        actor_tier=tier,
    )


def _message(
    message_id: str,
    *,
    sender: str = "alice",
    recipient: str = "bob",
    kind: AgentMessageKind = AgentMessageKind.TELL,
    conversation_id: str = "conversation-1",
    content: str | None = None,
) -> AgentMessage:
    return AgentMessage(
        id=message_id,
        tenant_id=T,
        conversation_id=conversation_id,
        sender=sender,
        recipient=recipient,
        kind=kind,
        content=content or f"content for {message_id}",
        run_id="run-1",
        authority=context_to_envelope(_context(sender)),
    )


class _Runner:
    def __init__(self, answer: str = "answer from bob") -> None:
        self.answer = answer
        self.calls = []

    async def respond(self, message, continuity, context):
        self.calls.append((message, continuity, context))
        return AgentResult.succeeded(
            {"text": self.answer}, summary=self.answer
        )


@pytest.mark.invariant("FLT-PEER-01")
async def test_build_org_composes_only_flat_tier1_named_peers() -> None:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    manifest = FleetManifest(
        organisation=T,
        tenant_id=T,
        named_agents=NamedAgentsConfig(
            default="alice",
            members=(
                NamedAgentConfig(name="Alice", address="alice", runtime="script"),
                NamedAgentConfig(name="Bob", address="bob", runtime="script"),
            ),
        ),
    )

    pump = build_org(kernel, build_spawner(kernel), manifest)

    assert pump._cos is None
    assert pump._flat_agents is True
    assert pump._default_agent == "alice"
    assert set(pump.named_agents) == {"alice", "bob"}
    assert all(agent._runtime.role == "tier1" for agent in pump.named_agents.values())
    assert all(agent.address == address for address, agent in pump.named_agents.items())


@pytest.mark.invariant("FLT-PEER-01")
@pytest.mark.invariant("CONV-AGENT-01")
async def test_ask_commits_one_reply_and_reply_does_not_loop() -> None:
    store = await _store()
    relay = EventRelay()
    alice, bob = _Runner("absorbed"), _Runner("Bob's considered answer")
    service = AgentMailboxService(
        store,
        {"alice": alice, "bob": bob},
        events=relay,
        worker_id="mailbox-worker",
    )
    ask = _message("ask-1", kind=AgentMessageKind.ASK)
    assert await store.enqueue_agent_message(ask)

    assert await service.run_once(T)
    conversation = await store.list_agent_conversation_messages(
        T, ask.conversation_id
    )
    assert [message.kind for message in conversation] == [
        AgentMessageKind.ASK,
        AgentMessageKind.REPLY,
    ]
    assert conversation[1].reply_to == ask.id
    assert conversation[1].content == "Bob's considered answer"
    assert bob.calls[0][2].actor == "bob"
    assert bob.calls[0][2].actor_tier == "tier1"
    assert bob.calls[0][2].grants.permits("agent.send")
    assert '<untrusted kind="agent_message"' in bob.calls[0][1]

    # The generated REPLY is delivered to Alice as a normal serialized turn,
    # but a REPLY never auto-generates another REPLY.
    assert await service.run_once(T)
    assert len(alice.calls) == 1
    assert len(await store.list_agent_conversation_messages(T, ask.conversation_id)) == 2
    inbox = await store.list_agent_inbox(T, "alice")
    assert inbox[0][1] == AgentDeliveryStatus.DELIVERED.value
    assert any(
        event.get("type") == "agent_message_reply"
        and event.get("content") == "Bob's considered answer"
        for event in relay.snapshot(T, "run-1")
    )


@pytest.mark.invariant("CONV-AGENT-01")
async def test_continuity_compacts_only_processed_history_plus_recent_tail() -> None:
    store = await _store()
    bob = _Runner()
    service = AgentMailboxService(
        store,
        {"bob": bob},
        worker_id="mailbox-worker",
        compaction_threshold=3,
        keep_recent=1,
    )
    for index in range(1, 5):
        await store.enqueue_agent_message(_message(f"tell-{index}"))

    await service.run_once(T)
    first_continuity = bob.calls[0][1]
    assert "content for tell-1" in first_continuity
    assert "content for tell-2" not in first_continuity

    for _ in range(3):
        await service.run_once(T)
    session = await store.get_agent_session(T, "bob", "conversation-1")
    assert session is not None
    summary = await store.get_latest_agent_session_summary(T, session.id)
    assert summary is not None
    assert summary.covered_count == 3
    assert summary.up_to_message_id == "tell-3"
    assert "Derived summary" in bob.calls[-1][1]
    assert '<untrusted kind="agent_session_summary"' in bob.calls[-1][1]
    assert "content for tell-4" in bob.calls[-1][1]


@pytest.mark.invariant("CONV-AGENT-01")
async def test_long_lived_dialogue_compacts_past_the_old_thousand_message_edge() -> None:
    store = await _store()
    service = AgentMailboxService(
        store,
        {"bob": _Runner()},
        compaction_threshold=40,
        keep_recent=12,
    )
    latest = None
    for index in range(1005):
        latest = _message(f"long-{index:04d}")
        await store.enqueue_agent_message(latest)
    assert latest is not None

    # Internal continuity is unbounded at the store seam and bounded before it
    # reaches a model. The old 1,000-row clamp made the current message vanish.
    await service._compact(latest)
    continuity = await service._continuity(latest)

    assert "Derived summary of messages 1-993" in continuity
    assert "Message 1 (tell)" not in continuity
    assert "content for long-1004" in continuity


@pytest.mark.invariant("REL-AGENT-01")
async def test_recipient_lease_serializes_workers_and_fences_stale_reply() -> None:
    store = await _store()
    original = _message("ask-lease", kind=AgentMessageKind.ASK)
    await store.enqueue_agent_message(original)

    first = await store.claim_next_agent_message(T, "worker-a", 60)
    assert first is not None
    assert await store.claim_next_agent_message(T, "worker-b", 60) is None

    expired = utcnow() - timedelta(seconds=1)
    key = (T, original.id)
    store._agent_deliveries[key] = replace(
        store._agent_deliveries[key], lease_expires_at=expired
    )
    store._agent_turn_leases[(T, "bob")] = replace(
        first.turn_lease, expires_at=expired
    )
    second = await store.claim_next_agent_message(T, "worker-b", 60)
    assert second is not None

    stale_reply = AgentMessage(
        id="reply-stale",
        tenant_id=T,
        conversation_id=original.conversation_id,
        sender="bob",
        recipient="alice",
        kind=AgentMessageKind.REPLY,
        content="stale",
        reply_to=original.id,
        authority=context_to_envelope(_context("bob")),
    )
    assert not await store.complete_agent_message(
        T, original.id, first.turn_lease, reply=stale_reply
    )
    winner = replace(stale_reply, id="reply-winner", content="winner")
    assert await store.complete_agent_message(
        T, original.id, second.turn_lease, reply=winner
    )
    assert not await store.complete_agent_message(
        T, original.id, second.turn_lease, reply=winner
    )
    messages = await store.list_agent_conversation_messages(T, original.conversation_id)
    assert [message.id for message in messages] == [original.id, "reply-winner"]


@pytest.mark.invariant("REL-AGENT-02")
async def test_turn_scheduler_orders_interactive_peer_then_background() -> None:
    store = await _store()
    held = await store.acquire_agent_turn(
        T, "bob", "holder", AgentTurnLane.INTERACTIVE, 60
    )
    assert held is not None

    # Queue background work first, then an interactive wake. Lane priority is a
    # scheduler property, so the later human turn still outranks the earlier job.
    assert await store.acquire_agent_turn(
        T, "bob", "background", AgentTurnLane.BACKGROUND, 60
    ) is None
    await store.enqueue_agent_message(_message("peer-priority"))
    assert await store.acquire_agent_turn(
        T, "bob", "interactive", AgentTurnLane.INTERACTIVE, 60
    ) is None
    assert await store.release_agent_turn(held)

    assert await store.claim_next_agent_message(T, "peer-worker", 60) is None
    interactive = await store.acquire_agent_turn(
        T, "bob", "interactive", AgentTurnLane.INTERACTIVE, 60
    )
    assert interactive is not None
    assert await store.release_agent_turn(interactive)

    peer = await store.claim_next_agent_message(T, "peer-worker", 60)
    assert peer is not None
    assert peer.turn_lease.lane is AgentTurnLane.PEER
    assert await store.complete_agent_message(
        T, peer.message.id, peer.turn_lease
    )

    background = await store.acquire_agent_turn(
        T, "bob", "background", AgentTurnLane.BACKGROUND, 60
    )
    assert background is not None
    assert await store.release_agent_turn(background)


@pytest.mark.invariant("SEC-AGENT-01")
@pytest.mark.invariant("FLT-PEER-02")
async def test_kernel_sender_is_unspoofable_and_ephemerals_have_no_mailbox_right() -> None:
    store = await _store()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["agent.send"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_agent_messages(store, events=kernel.events))

    output = await kernel.invoke(
        "agent",
        "agent.send",
        {"to": "bob", "content": "question", "kind": "ask"},
        _context("alice"),
    )
    stored = await store.get_agent_message(T, output["message_id"])
    assert stored is not None and stored.sender == "alice"

    with pytest.raises(SchemaValidationError):
        await kernel.invoke(
            "agent",
            "agent.send",
            {
                "from": "carol",
                "to": "bob",
                "content": "spoofed",
                "kind": "tell",
            },
            _context("alice"),
        )
    with pytest.raises(AdapterFailure, match="only a named tier-1"):
        await kernel.invoke(
            "agent",
            "agent.send",
            {"to": "bob", "content": "ephemeral attempt", "kind": "tell"},
            _context("alice", tier="ephemeral"),
        )

    # MCP run tokens preserve the tier instead of silently relabelling every
    # tool caller ephemeral; this is the actual Codex kernel-tools route.
    token = kernel.mcp.issue_run_token(
        T,
        GrantSet.of(["agent.send"]),
        actor="alice",
        actor_tier="tier1",
        run_id="mcp-run",
    )
    call = await kernel.mcp.handle(
        token,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "agent.send",
                "arguments": {"to": "bob", "content": "via MCP", "kind": "tell"},
            },
        },
    )
    assert call["result"]["isError"] is False

    with pytest.raises(FrozenInstanceError):
        stored.content = "mutated"  # type: ignore[misc]


async def test_missing_to_is_invalid_not_adapter_not_found() -> None:
    """agent.send with no recipient is a bad CALL, not a missing adapter.

    An agent invoking the tool with empty input used to fall through to the
    recipient lookup with address "" -> NOT_FOUND -> the kernel-wide
    'adapter_not_found' status, which read as "the adapter does not exist"
    in the chat projection (measured on the beelink, 2026-08-21). A missing
    parameter is INVALID; NOT_FOUND stays reserved for a real address that
    has no enabled peer, and now names the address it looked for.
    """
    store = await _store()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["agent.send"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_agent_messages(store, events=kernel.events))

    # The kernel's schema seam rejects {} outright (to/content/kind are
    # required), so the blank-address INVALID below is defence in depth for
    # any door that reaches the adapter without that seam.
    with pytest.raises(SchemaValidationError):
        await kernel.invoke("agent", "agent.send", {}, _context("alice"))

    adapter = build_agent_messages(store, events=kernel.events)
    direct = await adapter.execute("agent.send", {"to": ""}, None, _context("alice"))
    assert not direct.ok
    assert "requires 'to'" in str(direct.error)

    with pytest.raises(AdapterFailure, match="no enabled named agent at 'nobody'"):
        await kernel.invoke(
            "agent",
            "agent.send",
            {"to": "nobody", "content": "hi", "kind": "tell"},
            _context("alice"),
        )
