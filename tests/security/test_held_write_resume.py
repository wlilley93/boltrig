"""A write held for human approval inside a chat turn is actually carried out.

The ground truth this file exists for (live Classical Visas tenant, 2026-07-26):
a human approved ``opbox.add_comment`` at 11:41:52, the request sat ANSWERED and
never reached CONSUMED, and the comment was never posted. A chat turn carries a
run id but no work item, so the answer bridge had no route that could redeem the
approval - the instrument was recorded and nothing could claim it.

Decision 0018 closes it by replaying the RECORD OF THE CALL: the chokepoint seals
the canonical ``{noun, verb, params, ctx}`` and writes a ``held:`` checkpoint at
pause time, and the answer bridge re-invokes THAT under the ORIGINAL run identity,
so the approval fingerprint matches by construction and the ANSWERED -> CONSUMED
CAS remains the only thing deciding exactly-once.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from boltrig.api.bootstrap import wire_hitl_resume
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.kernel.credentials import held_call_cred_id
from boltrig.kernel.held_call import (
    HELD_STEP_PREFIX,
    any_held_call_paused,
    settle_held_call,
    sweep_run_credentials_if_settled,
)
from boltrig.kernel.hitl_expiry import expire_tenant_once
from boltrig.models import (
    ActionType,
    Conversation,
    ConversationStatus,
    CredentialResolution,
    GrantSet,
    HITLStatus,
    InvocationContext,
    MessageRole,
    PendingHuman,
    utcnow,
)
from tests.conftest import TENANT, _build_kernel

CONVERSATION = "conv-1"
ROOT_RUN = "chat-run-root"
CELL_RUN = "cell-run-child"


def _chat_ctx(run_id: str = CELL_RUN, parent: str | None = ROOT_RUN):
    """The context a chat turn's CELL dispatches under: the turn spawns a worker
    whose cell reaches back through the MCP face, so the verb runs on the child
    run while the client follows the root."""
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(["ticket.create"]),
        actor="chief-of-staff",
        actor_tier="tier1",
        run_id=run_id,
        parent_run_id=parent,
        on_behalf_of="alice",
        extra={"conversation_id": CONVERSATION, "principal_role": "member"},
    )


async def _chat_lane(**kernel_kw):
    """A gated kernel plus the chat service and answer bridge wired as in prod."""
    kernel, adapter = await _build_kernel(
        blocking_verbs={"ticket.create"}, **kernel_kw
    )
    await kernel.store.create_conversation(
        Conversation(
            id=CONVERSATION, tenant_id=TENANT, user_id="alice", title="t",
            status=ConversationStatus.ACTIVE,
        )
    )
    chat = ChatService(kernel.store, kernel.events, kernel=kernel)
    wire_hitl_resume(kernel, resume_held_write=chat.resume_held_write)
    return kernel, adapter, chat


async def _pause(kernel, title: str = "post the comment") -> str:
    with pytest.raises(PendingHuman) as pending:
        await kernel.invoke("ticket", "ticket.create", {"title": title}, _chat_ctx())
    return pending.value.hitl_request_id


def _held_checkpoints(kernel, run_id: str = ROOT_RUN):
    return [
        c
        for c in kernel.store._checkpoints.values()
        if c.run_id == run_id and c.step.startswith(HELD_STEP_PREFIX)
    ]


def _tool_calls(kernel, verb: str = "ticket.create"):
    rows = kernel.store._audit.get(TENANT, [])
    return [
        r for r in rows if r.action_type == ActionType.TOOL_CALL and r.verb == verb
    ]


# --- Order 2: the pause is durable at the chokepoint --------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_a_gated_chat_write_records_the_held_call_at_the_chokepoint():
    kernel, _adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)

    # a paused checkpoint on the ROOT run - the one a client follows and the one
    # the seal is keyed to - plus a pointer row on the child the verb was
    # dispatched on, because THAT is the run the answered request names.
    held = _held_checkpoints(kernel)
    assert len(held) == 1
    assert held[0].status == "paused" and held[0].hitl_request_id == request_id
    pointer = _held_checkpoints(kernel, CELL_RUN)
    assert len(pointer) == 1 and pointer[0].output == {"held_run_id": ROOT_RUN}
    assert pointer[0].step == held[0].step

    # the canonical call is sealed, and NOT in the checkpoint's plain-JSON output
    assert held[0].output is None
    sealed = kernel.store._creds[(TENANT, held_call_cred_id(ROOT_RUN, request_id))]
    assert "post the comment" not in str(sealed)  # sealed at rest (SEC-04)
    call = await kernel.store.get_credential_ref(
        TENANT, held_call_cred_id(ROOT_RUN, request_id)
    )
    assert call["kind"] == "held_call"
    assert call["value"]["verb"] == "ticket.create"
    assert call["value"]["params"] == {"title": "post the comment"}
    assert call["value"]["ctx"]["extra"]["conversation_id"] == CONVERSATION


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_a_held_call_can_never_be_resolved_back_into_a_verb_param():
    # Order 1. The seal carries the cell's OWN pending write verbatim, so if it
    # sat under the secure-answer kind a later param of this shape would resolve
    # it straight back into a param and hand the cell its held write to
    # exfiltrate. The distinct kind is the fence.
    kernel, _adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)
    reference = f"credential:run/{ROOT_RUN}/held_call:{request_id}"

    with pytest.raises(CredentialResolution):
        await kernel.credentials.resolve_run_scoped_params(
            TENANT, {"body": reference}, run_id=ROOT_RUN, owner="alice"
        )


# --- Orders 4 + 8: the approved write actually happens, exactly once ----------
@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_answering_the_approval_carries_out_the_held_write():
    kernel, adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)
    assert adapter._tickets == {}  # the gate held it: nothing ran

    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")

    # the ground truth's own discriminator: CONSUMED, not merely ANSWERED
    request = await kernel.hitl.get(TENANT, request_id)
    assert request.status == HITLStatus.CONSUMED
    assert [t["title"] for t in adapter._tickets.values()] == ["post the comment"]
    # the action is audited under the same run tree as the approval that bought it
    ok = [r for r in _tool_calls(kernel) if r.status == "ok"]
    assert len(ok) == 1 and ok[0].run_id == CELL_RUN and ok[0].parent_run_id == ROOT_RUN


@pytest.mark.security
@pytest.mark.invariant("NFR-REL-03")
async def test_delivering_the_resume_twice_executes_the_write_once():
    # The negative control. A duplicate delivery (a retried notifier, a second
    # answer route, an operator re-firing the bridge) must not run a
    # high-consequence write again, and must not add a second tool call to the
    # record either.
    kernel, adapter, chat = await _chat_lane()
    request_id = await _pause(kernel)

    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")
    first = [(r.verb, r.status) for r in _tool_calls(kernel)]
    # deliver it again exactly as a retried notifier would, and again straight at
    # the service, on both the dispatched run and the root
    await kernel.hitl._resume_notifier(await kernel.hitl.get(TENANT, request_id))
    await chat.resume_held_write(TENANT, CELL_RUN, request_id)
    await chat.resume_held_write(TENANT, ROOT_RUN, request_id)
    second = [(r.verb, r.status) for r in _tool_calls(kernel)]

    assert len(adapter._tickets) == 1
    consumed = [
        r for r in kernel.store._hitl.values() if r.status == HITLStatus.CONSUMED
    ]
    assert len(consumed) == 1
    # the pause row plus exactly ONE executed call, before and after
    assert first == [("ticket.create", "pending_human"), ("ticket.create", "ok")]
    assert second == first


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_only_the_sealed_params_can_execute_the_held_write():
    # The divergence test: no path executes a write whose params were not the
    # sealed canonical ones. Tampering with the seal cannot smuggle a different
    # action through, because the approval fingerprint binds the params verbatim.
    kernel, adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)
    cred_id = held_call_cred_id(ROOT_RUN, request_id)
    tampered = await kernel.store.get_credential_ref(TENANT, cred_id)
    tampered["value"]["params"] = {"title": "something else entirely"}
    await kernel.store.set_credential_ref(TENANT, cred_id, tampered)

    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")

    assert adapter._tickets == {}  # the tampered action never ran
    assert (await kernel.hitl.get(TENANT, request_id)).status == HITLStatus.ANSWERED
    # and it re-pends under a NEW request rather than silently executing
    resumed = [r for r in _tool_calls(kernel) if r.status == "ok"]
    assert resumed == []


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_a_missing_seal_refuses_and_never_guesses_the_call():
    # Order 6(i). An old request or a swept seal means the canonical action is
    # unknown; re-driving the transcript to guess it is expressly rejected.
    kernel, adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)
    await kernel.store.delete_credential_ref(
        TENANT, held_call_cred_id(ROOT_RUN, request_id)
    )

    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")

    assert adapter._tickets == {}
    request = await kernel.hitl.get(TENANT, request_id)
    assert request.status == HITLStatus.ANSWERED  # left unspent, never consumed
    notices = [
        r
        for r in kernel.store._audit.get(TENANT, [])
        if r.action_type == ActionType.HITL and r.status == "held_call_unreadable"
    ]
    assert len(notices) == 1
    told = [
        e for e in kernel.events.snapshot(TENANT, ROOT_RUN)
        if e.get("type") == "text_delta"
    ]
    assert told and "no longer on record" in told[0]["delta"]


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_the_continuation_reaches_the_stream_and_the_transcript():
    # Order 4(c). The turn's stream was closed when the turn ended, so the
    # continuation needs it reopened; and the relay evicts old closed streams, so
    # a 60-minute approval outlives the backlog unless the turn's transcript keeps
    # the outcome too.
    kernel, _adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)
    kernel.events.close(TENANT, ROOT_RUN)

    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")

    frames = kernel.events.snapshot(TENANT, ROOT_RUN)
    results = [e for e in frames if e.get("type") == "tool_result"]
    deltas = [e for e in frames if e.get("type") == "text_delta"]
    assert results and results[-1]["status"] == "ok"
    assert deltas and "ticket.create is done" in deltas[-1]["delta"]
    # bounded like every other chat frame: no params, no output values (K-20)
    assert "output" not in results[-1] and "input" not in results[-1]
    messages = await kernel.store.list_messages(TENANT, CONVERSATION)
    assert [m.role for m in messages] == [MessageRole.ASSISTANT]
    assert messages[0].run_id == ROOT_RUN


# --- Order 7: the seal never outlives the hold --------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_the_seal_is_dropped_when_the_approval_is_redeemed():
    kernel, _adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)
    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")

    assert not [k for k in kernel.store._creds if "held_call" in k[1]]
    assert [c.status for c in _held_checkpoints(kernel)] == ["done"]


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_the_expiry_janitor_drops_the_seal_of_an_unanswered_hold():
    # The chat lane never calls sweep_run_scoped (its only caller is the org
    # lane), so an approval that times out unanswered would leave its sealed
    # params behind for the life of the database.
    kernel, _adapter, _chat = await _chat_lane(approval_timeout_seconds=3600)
    request_id = await _pause(kernel)
    request = await kernel.hitl.get(TENANT, request_id)
    request.timeout_at = utcnow() - timedelta(seconds=1)

    assert await expire_tenant_once(kernel.store, TENANT) == 1

    assert (await kernel.hitl.get(TENANT, request_id)).status == HITLStatus.TIMED_OUT
    assert not [k for k in kernel.store._creds if "held_call" in k[1]]


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_rejecting_declines_cleanly_instead_of_asking_again():
    """A REJECT ends the matter; it must not silently ask a second time.

    Worth stating precisely, because adversarial review reported this as "a declined
    write is carried out anyway" and that is NOT what happens - I checked before
    believing it. The CAS refuses a non-approving decision, so the write never runs
    either way. What DID happen without an explicit decision check is that the resume
    walked on into the invoke, which re-pended: the record grew a SECOND
    `pending_human` request for a write the human had just declined, and the hold was
    left behind. A user who says no should not be asked again as though they had not.

    The seeded-failure check for this test is the re-pend, not the ticket: disable the
    decision check in resume_held_write and the tool_call rows go from one to two.
    """
    kernel, adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)

    await kernel.hitl.answer(TENANT, request_id, "reject", "boss@acme")

    assert adapter._tickets == {}, "a declined write must not execute"
    request = await kernel.hitl.get(TENANT, request_id)
    assert request.status != HITLStatus.CONSUMED, "nothing may be consumed on a reject"
    # THE DISCRIMINATOR: exactly one pause on the record, not a second ask.
    pending = [r for r in _tool_calls(kernel) if r.status == "pending_human"]
    assert len(pending) == 1, f"a reject must not re-pend; got {len(pending)} pauses"


# --- Order 7 extended: a run's secrets outlive the turn only while a hold does --
#
# The live gap these cover (Classical Visas, 2026-07-26): `sweep_run_scoped`'s only
# caller was the org pump, but the permission-parity bearer is sealed exclusively by
# the CHAT lane, which settles its own work item directly and never reaches that
# hook - and a delegated child has no work item at all, so nothing could ever sweep
# it. Both ends leaked a live caller-clamped external bearer for the life of the
# database: 29 rows on the live tenant, one root plus one child per turn, oldest a
# day old, none ever deleted.
#
# The rule the fix installs: a run's secrets live exactly as long as something can
# legitimately replay under that run, and not one moment longer.


def _bearer(kernel, run_id: str, owner: str = "alice"):
    return kernel.credentials.resolve_run_scoped_credential(TENANT, run_id, "opbox", owner)


async def _seal_bearer(kernel, run_id: str, token: str = "tok-abc") -> None:
    await kernel.credentials.seal_run_scoped_adapter_bearer(
        TENANT, run_id, "opbox", token, "alice"
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_a_paused_hold_keeps_the_run_secrets_its_own_resume_needs():
    """The guard, in the direction that MATTERS: a run terminal falling due while
    the gate holds a write must not sweep.

    `delete_credential_refs_for_run` deletes the whole `run:<id>:` prefix, so an
    unguarded sweep takes the parity bearer AND the sealed call with it - and the
    approved write could then never be carried out at all (Order 6(i) would refuse
    it as unreadable). The control at the end of this test is the seeded failure:
    it performs the UNGUARDED delete and shows both records die.
    """
    kernel, _adapter, _chat = await _chat_lane()
    await _seal_bearer(kernel, CELL_RUN)
    request_id = await _pause(kernel)

    # Both run terminals fall due here (the chat turn ends, the child returns)
    # while the approval is still outstanding. Neither may sweep.
    assert await sweep_run_credentials_if_settled(kernel.store, TENANT, CELL_RUN) == 0
    assert await sweep_run_credentials_if_settled(kernel.store, TENANT, ROOT_RUN) == 0

    # The resume replays under the CHILD's context, so it is the CHILD's bearer
    # that has to survive - the exact thing an `adapter_unauthorised` resume lacks.
    credential = await _bearer(kernel, CELL_RUN)
    assert credential is not None and credential.material["token"] == "tok-abc"
    assert await kernel.store.get_credential_ref(
        TENANT, held_call_cred_id(ROOT_RUN, request_id)
    ) is not None

    # SEEDED FAILURE / control: this is what an unguarded sweep does. If the guard
    # were absent, the two assertions above would fail exactly like this.
    await kernel.store.delete_credential_refs_for_run(TENANT, ROOT_RUN)
    await kernel.store.delete_credential_refs_for_run(TENANT, CELL_RUN)
    assert await _bearer(kernel, CELL_RUN) is None
    assert await kernel.store.get_credential_ref(
        TENANT, held_call_cred_id(ROOT_RUN, request_id)
    ) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_settling_the_hold_retires_the_bearer_the_turn_sealed():
    """The deferred sweep: once the hold is gone, the skipped run terminal falls due.

    Both ends, because a delegated call seals a bearer under each.
    """
    kernel, _adapter, _chat = await _chat_lane()
    await _seal_bearer(kernel, ROOT_RUN)
    await _seal_bearer(kernel, CELL_RUN)
    request_id = await _pause(kernel)
    assert await _bearer(kernel, CELL_RUN) is not None  # held: still alive

    await settle_held_call(kernel.store, TENANT, CELL_RUN, request_id)

    for run in (ROOT_RUN, CELL_RUN):
        assert await _bearer(kernel, run) is None, f"{run} bearer outlived its hold"


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_a_second_paused_hold_keeps_the_run_alive():
    """Settling ONE hold must not sweep a run another hold is still waiting on."""
    kernel, _adapter, _chat = await _chat_lane()
    await _seal_bearer(kernel, ROOT_RUN)
    first = await _pause(kernel, "first comment")
    second = await _pause(kernel, "second comment")
    assert first != second

    await settle_held_call(kernel.store, TENANT, CELL_RUN, first)

    assert await _bearer(kernel, ROOT_RUN) is not None, "the second hold still needs it"
    assert await kernel.store.get_credential_ref(
        TENANT, held_call_cred_id(ROOT_RUN, second)
    ) is not None

    await settle_held_call(kernel.store, TENANT, CELL_RUN, second)
    assert await _bearer(kernel, ROOT_RUN) is None, "the last hold settled; sweep falls due"


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_a_run_with_no_hold_is_swept_at_its_terminal():
    """The ordinary turn - no approval anywhere - retires its bearer immediately."""
    kernel, _adapter, _chat = await _chat_lane()
    await _seal_bearer(kernel, ROOT_RUN)

    assert await any_held_call_paused(kernel.store, TENANT, ROOT_RUN) is False
    assert await sweep_run_credentials_if_settled(kernel.store, TENANT, ROOT_RUN) == 1
    assert await _bearer(kernel, ROOT_RUN) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_both_ends_of_a_delegated_call_report_their_own_hold():
    """`any_held_call_paused` answers from either end: the root carries the real
    hold, the child a pointer row, and each terminal only knows its own run."""
    kernel, _adapter, _chat = await _chat_lane()
    request_id = await _pause(kernel)

    assert await any_held_call_paused(kernel.store, TENANT, ROOT_RUN) is True
    assert await any_held_call_paused(kernel.store, TENANT, CELL_RUN) is True
    assert await any_held_call_paused(kernel.store, TENANT, "some-other-run") is False

    await settle_held_call(kernel.store, TENANT, CELL_RUN, request_id)
    assert await any_held_call_paused(kernel.store, TENANT, ROOT_RUN) is False
    assert await any_held_call_paused(kernel.store, TENANT, CELL_RUN) is False


@pytest.mark.security
@pytest.mark.invariant("SEC-181")
async def test_a_chat_turn_retires_the_bearer_it_sealed():
    """End to end on the lane that actually leaked.

    The turn seals the caller's clamped bearer before any dispatch and must have
    retired it by the time the turn is terminal. The mid-turn probe is what makes
    this discriminate: asserting only that the bearer is gone afterwards would
    pass just as happily if the turn had never sealed one.
    """
    kernel, _adapter, _chat = await _chat_lane()
    seen: dict[str, object] = {}

    class _StubSpawner:
        async def spawn(self, tenant_id, task, skills, prefer, context, **kwargs):
            seen["mid_turn"] = await kernel.credentials.resolve_run_scoped_credential(
                TENANT, context.run_id, "opbox", "alice"
            )
            return {"summary": "did it"}

    chat = ChatService(
        kernel.store, kernel.events,
        turn_executor=build_turn_executor(kernel, _StubSpawner(), continuity=False),
    )
    _ = [
        event
        async for event in chat.handle_turn(
            tenant_id=TENANT, user_id="alice", role="member",
            message="do the thing", on_behalf_bearer="tok-xyz",
        )
    ]

    assert seen["mid_turn"] is not None, "the turn must seal the caller's bearer"
    turn = next(
        i for i in await kernel.store.list_work_items(TENANT) if i.parent_id is None
    )
    assert await kernel.credentials.resolve_run_scoped_credential(
        TENANT, turn.id, "opbox", "alice"
    ) is None, "the turn's sealed bearer outlived the turn"


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_a_resumed_held_write_reaches_the_adapter_with_the_callers_bearer():
    """The defect that made the FIRST live acceptance attempt fail, locked down.

    On cvboltrig the approval reached CONSUMED and the held call was re-invoked, and
    the comment still was not posted: the adapter received the STATIC service
    credential instead of the caller's, and the opbox door answered
    `adapter_unauthorised`. So `consumed` is NOT by itself proof the write happened,
    and I nearly reported it as one. What actually carries the approver's authority
    downstream is the run-scoped bearer resolved at dispatch, and nothing asserted
    it survived the pause and reached the adapter on the RESUMED call. Now it does.
    """
    kernel, adapter, _chat = await _chat_lane()
    # sealed against the CELL run, because the resume replays the sealed context and
    # `resolve_run_scoped_credential` keys on that context's run id, not the root's
    await kernel.credentials.seal_run_scoped_adapter_bearer(
        TENANT, CELL_RUN, adapter.id, "caller-bearer-xyz", "alice"
    )
    seen: dict[str, object] = {}
    original = adapter.execute

    async def _capture(verb, params, credential, context):
        seen["credential"] = credential
        return await original(verb, params, credential, context)

    adapter.execute = _capture
    request_id = await _pause(kernel)
    assert "credential" not in seen, "the gate must hold it before any adapter call"

    await kernel.hitl.answer(TENANT, request_id, "approve", "boss@acme")

    assert (await kernel.hitl.get(TENANT, request_id)).status == HITLStatus.CONSUMED
    credential = seen.get("credential")
    assert credential is not None, "the resumed write reached the adapter with NO credential"
    assert credential.material["token"] == "caller-bearer-xyz", (
        "the resumed write ran under the static service credential instead of the "
        "approver's authority - that is the adapter_unauthorised failure"
    )
