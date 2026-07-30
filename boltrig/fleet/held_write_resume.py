"""Replay a held write once a human has approved it (decision 0018, Orders 4/6/7).

The ratio: a held write is resumed by replaying the RECORD OF THE CALL, not by
replaying the agent that produced it. So this never re-drives a transcript and
never mints a run id. It reads the ``held:`` checkpoint and the sealed canonical
call the chokepoint wrote at pause time (``kernel/held_call.py``), reopens the
run's event stream, and re-enters ``kernel.invoke`` with those exact params under
the ORIGINAL run identity - which is what makes ``approval_request_fingerprint``
match by construction and leaves ``consume_approved_by`` as the sole authority on
exactly-once (SEC-14).

It must publish through the deployment's run ``EventRelay``. Redis shares that
relay across production replicas; development still uses the same local Kernel
instance so the browser and resume publisher meet on one stream.

Candour, never silence and never a silent re-pend. Three residual paths are
recorded on the run stream AND in the audit trail rather than swallowed: the
sealed call is gone (refuse - the canonical action is unknown and guessing it is
the probabilistic failure the seal exists to remove), the resumed invoke re-pends
because the resource genuinely changed during the approval window (say so, and
surface the NEW request id), and the approval was already spent (the write ran;
say so rather than asking again).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from boltrig.kernel.held_call import (
    HeldCall,
    held_run_id,
    held_write_is_waiting,
    read_held_call,
    settle_held_call,
)
from boltrig.models import (
    ActionType,
    AuditEvent,
    BoltrigError,
    ConversationMessage,
    HITLStateConflict,
    HITLStatus,
    HITLType,
    MessageRole,
    PendingHuman,
    utcnow,
)

log = logging.getLogger("boltrig.fleet.held_write_resume")

# The audited verb name for a resume outcome. It is a HITL action, never a
# TOOL_CALL: the tool call itself is audited by the chokepoint, and exactly one
# TOOL_CALL row per redeemed approval is the property the negative control pins.
RESUME_VERB = "hitl.held_write.resume"


def _frames(call_id: str | None, status: str, text: str) -> list[dict[str, Any]]:
    """The continuation's frames, in the BOUNDED chat shape (K-20).

    ``call_id`` is the one the pause was recorded under, so a client pairs this
    result with the ``hitl`` frame it is still showing; without one there is no
    tool result to report and only the sentence rides. Values never ride: the
    verb's real output went to the caller and to the audit row, and the chat
    stream carries only status + a short human sentence, exactly as
    ``chat._project_chat_event`` bounds a live turn.
    """
    frames: list[dict[str, Any]] = []
    if call_id:
        frames.append(
            {"type": "tool_result", "call_id": call_id, "status": status,
             "result_summary": {"status": status}}
        )
    frames.append({"type": "text_delta", "delta": text})
    return frames


async def _record(
    kernel: Any, held: HeldCall, run_id: str, status: str, detail: dict[str, Any]
) -> None:
    """Audit one resume outcome under the ORIGINAL run, so the approval and what
    became of it render in the one tree ``/v1/audit/tree/{run_id}`` draws."""
    context = held.context
    await kernel.audit.write(
        AuditEvent(
            tenant_id=context.tenant_id,
            ts=utcnow(),
            run_id=run_id,
            actor=context.actor,
            actor_tier=context.actor_tier,
            action_type=ActionType.HITL,
            verb=RESUME_VERB,
            noun=held.noun or None,
            on_behalf_of=context.on_behalf_of,
            workspace_id=context.workspace_id,
            status=status,
            detail={"hitl_request_id": held.request_id, "held_verb": held.verb, **detail},
        )
    )


async def _publish(
    relay: Any, tenant_id: str, run_id: str, frames: list[dict[str, Any]]
) -> None:
    """Publish the continuation to the run's stream and close it again.

    Fail-safe (P9): the write has already happened and is audited, so a relay
    fault must never turn a successful resume into an error."""
    try:
        for frame in frames:
            relay.publish(tenant_id, run_id, {**frame, "run_id": run_id})
        relay.close(tenant_id, run_id)
    except Exception:  # noqa: BLE001 - the stream is the side channel, not the record
        log.warning("held-write continuation could not be streamed", exc_info=True)


async def _append_continuation(
    store: Any, held: HeldCall, run_id: str, frames: list[dict[str, Any]]
) -> None:
    """Persist the continuation as a new assistant message on the conversation.

    Necessary because the relay evicts the oldest closed streams past
    ``max_closed``: a 60-minute approval on a busy tenant outlives the backlog, so
    a client that reloads after the fact would see the pause and never its
    outcome. The conversation is DERIVED from the sealed context envelope (it is
    already in ``ctx.extra``) - no new column, no fingerprint index.
    """
    conversation_id = held.context.extra.get("conversation_id")
    if not conversation_id:
        return  # not a conversational lane: the run stream + audit are the record
    tenant_id = held.context.tenant_id
    text = "".join(f.get("delta", "") for f in frames if f.get("type") == "text_delta")
    try:
        await store.add_message(
            ConversationMessage(
                id=uuid.uuid4().hex, conversation_id=str(conversation_id),
                tenant_id=tenant_id, role=MessageRole.ASSISTANT, content=text,
                run_id=run_id, events=frames,
            )
        )
        conversation = await store.get_conversation(tenant_id, str(conversation_id))
        if conversation is not None:
            conversation.updated_at = utcnow()
            await store.update_conversation(conversation)
    except Exception:  # noqa: BLE001 - the write stands; its transcript entry is best-effort
        log.warning("held-write continuation could not be persisted", exc_info=True)


async def _claimable(kernel: Any, tenant_id: str, run_id: str, request_id: str) -> bool:
    """Whether this answered approval is still ours to redeem.

    The first line of the exactly-once defence, and the cheap one: a request that
    is not an ANSWERED approval has already been spent, expired, or was never
    ours. The authority remains the ANSWERED -> CONSUMED CAS underneath; this only
    keeps a duplicate delivery from re-entering the chokepoint at all, so the
    audit trail carries ONE tool call for one approval rather than one plus a
    conflict.
    """
    request = await kernel.hitl.get(tenant_id, request_id)
    if request is None or request.type != HITLType.APPROVAL:
        return False
    if request.status != HITLStatus.ANSWERED:
        return False
    return await held_write_is_waiting(kernel.store, tenant_id, run_id, request_id)


async def _refuse_unreadable(
    kernel: Any, relay: Any, tenant_id: str, run_id: str, stream: str, request_id: str
) -> dict[str, Any]:
    """The sealed call is missing or unreadable: REFUSE, loudly (Order 6(i)).

    The approval is left ANSWERED and unspent. Re-driving the transcript to guess
    what was approved is expressly rejected: it re-imports the probabilistic
    failure the record exists to remove.
    """
    request = await kernel.hitl.get(tenant_id, request_id)
    verb = getattr(request, "verb", None) or "the held action"
    text = (
        f"I could not carry out {verb}: the approved call is no longer on record, "
        "so I will not guess at it. The approval stands unused - please ask again."
    )
    await kernel.audit.write(
        AuditEvent(
            tenant_id=tenant_id, ts=utcnow(), run_id=stream, actor="hitl-resume",
            actor_tier="tier1", action_type=ActionType.HITL, verb=RESUME_VERB,
            status="held_call_unreadable",
            detail={"hitl_request_id": request_id, "held_verb": verb},
        )
    )
    relay.reopen(tenant_id, stream)
    await _publish(relay, tenant_id, stream, _frames(None, "unreadable", text))
    await settle_held_call(kernel.store, tenant_id, run_id, request_id)
    return {"status": "refused", "reason": "held_call_unreadable"}


async def _invoke_held(
    kernel: Any, held: HeldCall, run_id: str
) -> tuple[str, str, dict[str, Any]]:
    """Re-enter the ONE chokepoint with the recorded call. Returns
    (status, human sentence, audit detail).

    The params come from the seal and the run identity is unchanged, so the
    fingerprint matches by construction; every outcome below is a fact about the
    action, never a re-ask.
    """
    try:
        await kernel.invoke(
            held.noun, held.verb, held.params, held.context,
            approval_id=held.request_id,
        )
        return "ok", f"Approved - {held.verb} is done.", {}
    except PendingHuman as pending:
        # SEC-14 working correctly: _resource_context is re-read live, and the
        # resource legitimately changed while the approval was pending, so the
        # old approval no longer authorises this action. Say WHY, and surface the
        # new request rather than presenting it as a fresh unexplained ask.
        return (
            "re_pended",
            f"{held.verb} was not carried out: what it acts on changed while the "
            "approval was pending, so it needs approving again.",
            {"new_hitl_request_id": pending.hitl_request_id},
        )
    except HITLStateConflict:
        # The approval was already spent: the write RAN. Telling the user to
        # approve again would invite a second execution of a high-consequence
        # action that already happened.
        return (
            "already_ran",
            f"{held.verb} had already been carried out with this approval, so I "
            "did not run it again.",
            {},
        )
    except BoltrigError as exc:
        return (
            exc.reason,
            f"{held.verb} was approved but failed to run ({exc.reason}).",
            {"error": exc.reason},
        )
    except Exception as exc:  # noqa: BLE001 - an adapter fault is an outcome, not silence
        # The approval was spent by the gate before the adapter ran, so it can
        # never be re-spent: swallowing this would leave a human believing an
        # approved write happened. Only the type name persists (K-20).
        return (
            "error",
            f"{held.verb} was approved but failed to run ({type(exc).__name__}).",
            {"error": type(exc).__name__},
        )


async def resume_held_write(
    kernel: Any, store: Any, relay: Any, tenant_id: str, run_id: str, request_id: str
) -> dict[str, Any]:
    """Replay the write this approval authorised, on the run that asked for it.

    ``run_id`` is the run the ANSWERED request names (the one the verb was
    dispatched on); the continuation goes to the run a client actually follows,
    which the record points at.
    """
    if not await _claimable(kernel, tenant_id, run_id, request_id):
        return {"status": "skipped"}
    stream = await held_run_id(store, tenant_id, run_id, request_id)
    # A REJECT MUST NOT EXECUTE. The bridge fires on any ANSWER, approve or not, so
    # without this the decision is never read and a declined write is carried out
    # anyway - the precise inversion of the gate's purpose, and worse than the
    # never-executes defect this whole change repairs. Found by adversarial review,
    # which reached it by rejecting rather than approving; the happy path hides it
    # completely because consume_approved_by is only reached further down.
    #
    # Settle the hold on the way out: a declined write is terminal, so leaving the
    # seal behind would outlive its run (Order 7 applies to every outcome, not only
    # redeemed ones).
    if not await kernel.hitl.is_approved(tenant_id, request_id):
        held = await read_held_call(store, tenant_id, run_id, request_id)
        relay.reopen(tenant_id, stream)
        declined = _frames(None, "declined", "That was declined, so I have not carried it out.")
        await _publish(relay, tenant_id, stream, declined)
        if held is not None:
            from boltrig.kernel.realtime_call_bridge import (
                project_realtime_hitl_outcome,
            )

            await project_realtime_hitl_outcome(store, held, "declined")
        await settle_held_call(store, tenant_id, run_id, request_id)
        return {"status": "declined"}
    held = await read_held_call(store, tenant_id, run_id, request_id)
    if held is None:
        return await _refuse_unreadable(kernel, relay, tenant_id, run_id, stream, request_id)
    # Reopen BEFORE the write so the continuation has somewhere to land: the turn
    # closed its stream when it ended, and subscribe() returns immediately for a
    # closed key. The write itself never depends on it.
    relay.reopen(tenant_id, stream)
    status, text, detail = await _invoke_held(kernel, held, stream)
    await _record(kernel, held, stream, status, detail)
    from boltrig.kernel.realtime_call_bridge import project_realtime_hitl_outcome

    await project_realtime_hitl_outcome(
        store,
        held,
        status,
        new_request_id=detail.get("new_hitl_request_id"),
    )
    # Retire the hold on EVERY outcome (Order 7): redeemed, conflicted, re-pended
    # under a new request, or failed. The chat lane never calls sweep_run_scoped,
    # so a seal left behind here outlives its run.
    await settle_held_call(store, tenant_id, run_id, request_id)
    frames = _frames(held.call_id, status, text)
    await _append_continuation(store, held, stream, frames)
    await _publish(relay, tenant_id, stream, frames)
    return {"status": status, **detail}
