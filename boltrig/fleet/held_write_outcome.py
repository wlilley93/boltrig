"""How a resumed held write is TOLD and RECORDED, apart from how it is resumed.

Split out of ``held_write_resume`` on 2026-08-07, when closing the decline gap
pushed that module past the structure limits. The seam is real rather than
convenient: everything here answers "what does the world learn about this
outcome" - the bounded chat frames, the run stream, the conversation, the audit
row - while the resume module decides WHICH outcome occurred.

The rule the split makes visible: every outcome is told the same four ways, and a
path that skips one is the defect. The decline skipped three of them for months
precisely because it was the ordinary case and nobody read it as a path at all.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from boltrig.kernel.held_call import HeldCall
from boltrig.models import (
    ActionType,
    AuditEvent,
    ConversationMessage,
    MessageRole,
    utcnow,
)

log = logging.getLogger("boltrig.fleet.held_write_outcome")

# The audited verb name for a resume outcome. It is a HITL action, never a
# TOOL_CALL: the tool call itself is audited by the chokepoint, and exactly one
# TOOL_CALL row per redeemed approval is the property the negative control pins.
RESUME_VERB = "hitl.held_write.resume"

# How much of a human's stated reasoning rides the chat stream (the rest stays on
# the response row and in the audit detail). Long enough for a real sentence,
# short enough that the bounded frame stays bounded.
MAX_DECISION_REASON = 280



def frames(call_id: str | None, status: str, text: str) -> list[dict[str, Any]]:
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


async def record(
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


async def decision_reason(kernel: Any, tenant_id: str, request_id: str) -> str:
    """The human's own words for WHY, bounded. Read on EVERY outcome.

    Read on approvals too, and not for symmetry's sake: the notes field in the UI
    (``HitlRespond.tsx``) is labelled "Your reasoning is recorded in the audit
    trail", and until 2026-08-07 that sentence was false in both directions. It
    went to the response row and to nothing else. A promise a product makes to
    the person operating a gate is the kind that has to be true.

    ``HITLResponse.notes`` has been captured at ``POST /v1/hitl/{id}/respond``,
    written to the store and read back out of it since the HITL lane was built,
    and NOTHING downstream has ever read it. So every declined write reached the
    agent as a bare "declined", which is the one refusal an agent answers by
    trying the same thing again.

    Bounded because this rides the chat stream, where K-20 admits a status and a
    short human sentence and nothing else. The cap elides; it never drops the
    reason, and the full text stays on the response row either way.
    """
    try:
        response = await kernel.store.get_hitl_response(tenant_id, request_id)
    except Exception:  # noqa: BLE001 - an unreadable reason must never void a decision
        log.warning("decision reason could not be read", exc_info=True)
        return ""
    notes = (getattr(response, "notes", "") or "").strip()
    if len(notes) > MAX_DECISION_REASON:
        return notes[: MAX_DECISION_REASON - 3].rstrip() + "..."
    return notes


async def record_decline(
    kernel: Any,
    tenant_id: str,
    stream: str,
    request_id: str,
    held: HeldCall | None,
    reason: str,
) -> None:
    """Audit the decline itself.

    The module docstring above enumerates three residual paths that reach the
    audit trail rather than being swallowed. The ORDINARY decline was not among
    them, because it did not read as residual - and so the single most
    governance-relevant outcome an approval gate produces, a human refusing a
    high-consequence write, left no row at all. ``ActionType.HITL`` occurred
    exactly twice in the tree before this, on the unreadable-seal path and the
    redeemed path, neither of which a decline ever takes.

    Unwrapped, like ``_record``: an audit failure here is loud, because the row
    IS the record.
    """
    detail: dict[str, Any] = {"hitl_request_id": request_id}
    if held is not None:
        detail["held_verb"] = held.verb
    if reason:
        detail["decision_reason"] = reason
    context = held.context if held is not None else None
    await kernel.audit.write(
        AuditEvent(
            tenant_id=tenant_id,
            ts=utcnow(),
            run_id=stream,
            actor=context.actor if context is not None else "hitl-resume",
            actor_tier=context.actor_tier if context is not None else "tier1",
            action_type=ActionType.HITL,
            verb=RESUME_VERB,
            noun=(held.noun or None) if held is not None else None,
            on_behalf_of=context.on_behalf_of if context is not None else None,
            workspace_id=context.workspace_id if context is not None else None,
            status="declined",
            detail=detail,
        )
    )


async def publish(
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


async def append_continuation(
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
                author_agent_address=held.context.actor,
            )
        )
        conversation = await store.get_conversation(tenant_id, str(conversation_id))
        if conversation is not None:
            conversation.updated_at = utcnow()
            await store.update_conversation(conversation)
    except Exception:  # noqa: BLE001 - the write stands; its transcript entry is best-effort
        log.warning("held-write continuation could not be persisted", exc_info=True)
