"""Sequential chat-turn and mid-run steer orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from boltrig.models import (
    ConversationMessage,
    GrantSet,
    MessageRole,
    ModelEndpointUnavailable,
    utcnow,
)

from .chat_attachments import validate_attachments
from .chat_conversation_access import (
    ConversationAgentSwitchBusy,
    ConversationAgentSwitchConflict,
    ConversationForbidden,
    ConversationProjectContextMismatch,
    resolve_conversation,
)
from .chat_idempotency import replay_if_duplicate


@dataclass(frozen=True)
class TurnRequest:
    tenant_id: str
    user_id: str
    role: str
    message: str
    conversation_id: str | None
    agent_address: str | None
    grants: GrantSet | None
    attachments: list[dict[str, Any]] | None
    workspace_id: str | None
    scope: dict[str, Any] | None
    on_behalf_bearer: str | None
    idempotency_key: str | None
    origin: str | None
    model_profile_id: str | None
    model_choice_id: str | None
    caller_context: Any
    input_role: MessageRole


def decision_request_id(events: list[dict[str, Any]]) -> str | None:
    """Return the first canonical HITL id from approval or question frames."""
    for event in events:
        if event.get("type") == "hitl" and event.get("hitl_request_id"):
            return str(event["hitl_request_id"])
        if event.get("type") == "question" and event.get("question_id"):
            return str(event["question_id"])
    return None


async def _reserve_or_queue(service, request, selection, records, run_id):
    conversation = selection.conversation
    async with service._lock_for(request.tenant_id, conversation.id):  # noqa: SLF001
        turn_agent_address = await _refresh_admission_projection(service, request, selection)
        active_run_id = service._active_run_for(  # noqa: SLF001
            request.tenant_id, conversation.id
        )
        if active_run_id is None:
            await _switch_conversation_agent(
                service, request.tenant_id, conversation, turn_agent_address
            )
            # Claim active ownership before writing the direct input, while the
            # same cross-replica lock prevents a steer overtaking either step.
            # A store failure rolls the claim back; a Redis failure occurs
            # before any message is persisted.
            service._set_active_run(  # noqa: SLF001
                request.tenant_id, conversation.id, run_id
            )
            try:
                await _persist_direct_input(
                    service,
                    request,
                    conversation.id,
                    records,
                    run_id,
                    turn_agent_address,
                )
            except BaseException:
                service._clear_active_run(  # noqa: SLF001
                    request.tenant_id, conversation.id, expected=run_id
                )
                raise
            return None
        if turn_agent_address != conversation.agent_address:
            raise ConversationAgentSwitchBusy(
                "the selected agent can be changed after the active turn finishes"
            )
        if request.model_choice_id:
            # A steer joins the already-running request and cannot alter the
            # immutable model admission being provisioned for it. Worker locks
            # the switcher while busy; the HTTP door enforces the same truth.
            raise ModelEndpointUnavailable(
                "a model choice cannot change while a conversation turn is active"
            )
        message_id = uuid.uuid4().hex
        await service._store.enqueue_conversation_steer(  # noqa: SLF001
            ConversationMessage(
                id=message_id,
                conversation_id=conversation.id,
                tenant_id=request.tenant_id,
                role=request.input_role,
                content=request.message,
                attachments=records,
                run_id=run_id,
                recipient_agent_address=turn_agent_address,
            )
        )
    frame = {
        "type": "steer_queued",
        "run_id": active_run_id,
        "conversation_id": conversation.id,
        "message_id": message_id,
        "agent_address": turn_agent_address,
        "queued_run_id": run_id,
    }
    service._relay.publish(request.tenant_id, active_run_id, frame)  # noqa: SLF001
    return {**frame, "type": "queued"}


async def _switch_conversation_agent(service, tenant_id, conversation, turn_agent_address):
    if turn_agent_address == conversation.agent_address:
        return
    if turn_agent_address is None:
        raise ConversationAgentSwitchConflict(
            "a named-agent conversation cannot be switched to no agent"
        )
    switched = await service._store.switch_conversation_agent(  # noqa: SLF001
        tenant_id,
        conversation.id,
        conversation.agent_address,
        turn_agent_address,
    )
    if switched != turn_agent_address:
        raise ConversationAgentSwitchConflict(
            "the conversation's selected agent changed concurrently"
        )
    conversation.agent_address = switched


async def _refresh_admission_projection(service, request, selection):
    """Refresh mutable routing while the caller holds the conversation lock."""
    conversation = selection.conversation
    current = await service._store.get_conversation(  # noqa: SLF001
        request.tenant_id, conversation.id
    )
    if current is None:
        raise ConversationForbidden("no such conversation")
    if current.workspace_id is not None and current.workspace_id != request.workspace_id:
        raise ConversationProjectContextMismatch(
            "switch to this conversation's project before continuing it"
        )
    conversation.workspace_id = current.workspace_id
    conversation.agent_address = current.agent_address
    if request.agent_address is None and current.agent_address is not None:
        # Implicit sends follow the latest responder; explicit chip selections
        # remain compare-and-set requests in _reserve_or_queue.
        return current.agent_address
    return selection.agent_address


async def _persist_direct_input(
    service,
    request: TurnRequest,
    conversation_id: str,
    records,
    run_id: str,
    turn_agent_address: str | None,
) -> None:
    await service._store.add_message(  # noqa: SLF001
        ConversationMessage(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            tenant_id=request.tenant_id,
            role=request.input_role,
            content=request.message,
            attachments=records,
            run_id=run_id,
            recipient_agent_address=turn_agent_address,
        )
    )


async def _stream_one(
    service,
    request,
    conversation,
    run_id,
    message,
    records,
    consumed_steer_id,
    collected,
    turn_agent_address,
):
    if consumed_steer_id is not None:
        yield {
            "type": "steer_consumed",
            "run_id": run_id,
            "conversation_id": conversation.id,
            "message_id": consumed_steer_id,
            "agent_address": turn_agent_address,
        }
    yield {
        "type": "message_start",
        "run_id": run_id,
        "conversation_id": conversation.id,
        "agent_address": turn_agent_address,
    }
    async for event in service._drive(  # noqa: SLF001
        request.tenant_id,
        request.user_id,
        conversation.id,
        run_id,
        message,
        request.role,
        request.grants,
        records,
        agent_address=turn_agent_address,
        workspace_id=request.workspace_id,
        scope=request.scope,
        on_behalf_bearer=request.on_behalf_bearer,
        origin=request.origin,
        model_profile_id=request.model_profile_id,
        model_choice_id=getattr(request, "model_choice_id", None),
        caller_context=getattr(request, "caller_context", None),
    ):
        if not service._refresh_active_run(  # noqa: SLF001
            request.tenant_id, conversation.id, expected=run_id
        ):
            raise RuntimeError("conversation_run_ownership_lost")
        if event.get("type") != "heartbeat":
            collected.append(event)
        yield event
    yield {"type": "message_end", "run_id": run_id}


async def _persist_assistant(
    service, request, conversation, run_id: str, collected, turn_agent_address
) -> None:
    text = "".join(
        event.get("delta", "") for event in collected if event.get("type") == "text_delta"
    )
    hitl_id = decision_request_id(collected)
    await service._store.add_message(  # noqa: SLF001
        ConversationMessage(
            id=uuid.uuid4().hex,
            conversation_id=conversation.id,
            tenant_id=request.tenant_id,
            role=MessageRole.ASSISTANT,
            content=text,
            run_id=run_id,
            hitl_request_id=hitl_id,
            events=collected,
            author_agent_address=turn_agent_address,
        )
    )
    conversation.updated_at = utcnow()
    await service._store.update_conversation(conversation)  # noqa: SLF001
    await service._maybe_compact(request.tenant_id, conversation.id)  # noqa: SLF001


async def _next_turn(service, request, conversation, current_run_id):
    async with service._lock_for(request.tenant_id, conversation.id):  # noqa: SLF001
        if (
            service._active_run_for(  # noqa: SLF001
                request.tenant_id, conversation.id
            )
            != current_run_id
        ):
            return None
        fallback_run_id = uuid.uuid4().hex
        steer = await service._next_pending_steer(  # noqa: SLF001
            request.tenant_id, conversation.id, fallback_run_id
        )
        if steer is None:
            service._clear_active_run(  # noqa: SLF001
                request.tenant_id,
                conversation.id,
                expected=current_run_id,
            )
            return None
        run_id = steer.run_id or fallback_run_id
        service._set_active_run(  # noqa: SLF001
            request.tenant_id, conversation.id, run_id
        )
    return run_id, steer


async def _selection_or_replay(service, request):
    # Existing-thread authority and requested agent selection are checked
    # before a retry marker can be consumed. A mismatched retry must remain a
    # refusal, not look like an accepted duplicate.
    selection = None
    if request.conversation_id:
        selection = await resolve_conversation(
            service._store,  # noqa: SLF001
            request.tenant_id,
            request.conversation_id,
            request.user_id,
            request.role,
            request.message,
            request.agent_address,
            request.workspace_id,
        )
    replay = await replay_if_duplicate(
        service._store,  # noqa: SLF001
        request.tenant_id,
        request.idempotency_key,
        request.conversation_id,
    )
    if replay is not None:
        return None, replay
    if selection is None:
        selection = await resolve_conversation(
            service._store,  # noqa: SLF001
            request.tenant_id,
            request.conversation_id,
            request.user_id,
            request.role,
            request.message,
            request.agent_address,
            request.workspace_id,
        )
    return selection, None


async def stream_turn(service, request: TurnRequest):
    records = validate_attachments(request.attachments, service._cfg)  # noqa: SLF001
    selection, replay = await _selection_or_replay(service, request)
    if replay is not None:
        for frame in replay:
            yield frame
        return
    assert selection is not None
    conversation = selection.conversation
    run_id = uuid.uuid4().hex
    queued = await _reserve_or_queue(service, request, selection, records, run_id)
    if queued is not None:
        yield queued
        return
    try:
        message, consumed_id = request.message, None
        turn_agent_address = selection.agent_address
        while True:
            collected: list[dict[str, Any]] = []
            async for event in _stream_one(
                service,
                request,
                conversation,
                run_id,
                message,
                records,
                consumed_id,
                collected,
                turn_agent_address,
            ):
                yield event
            await _persist_assistant(
                service,
                request,
                conversation,
                run_id,
                collected,
                turn_agent_address,
            )
            if any(event.get("type") == "cancelled" for event in collected):
                return
            next_turn = await _next_turn(service, request, conversation, run_id)
            if next_turn is None:
                return
            run_id, steer = next_turn
            message, records = steer.content or "", steer.attachments
            consumed_id = steer.id
            turn_agent_address = steer.recipient_agent_address
    finally:
        async with service._lock_for(  # noqa: SLF001
            request.tenant_id, conversation.id
        ):
            service._clear_active_run(  # noqa: SLF001
                request.tenant_id,
                conversation.id,
                expected=run_id,
            )
