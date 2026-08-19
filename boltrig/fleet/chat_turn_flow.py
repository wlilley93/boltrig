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
from .chat_conversation_access import resolve_conversation
from .chat_idempotency import replay_if_duplicate


@dataclass(frozen=True)
class TurnRequest:
    tenant_id: str
    user_id: str
    role: str
    message: str
    conversation_id: str | None
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


async def _reserve_or_queue(service, request, conversation, records, run_id):
    async with service._lock_for(request.tenant_id, conversation.id):  # noqa: SLF001
        active_run_id = service._active_run_for(  # noqa: SLF001
            request.tenant_id, conversation.id
        )
        if active_run_id is None:
            # Claim active ownership before writing the direct input, while the
            # same cross-replica lock prevents a steer overtaking either step.
            # A store failure rolls the claim back; a Redis failure occurs
            # before any message is persisted.
            service._set_active_run(  # noqa: SLF001
                request.tenant_id, conversation.id, run_id
            )
            try:
                await _persist_direct_input(service, request, conversation.id, records, run_id)
            except BaseException:
                service._clear_active_run(  # noqa: SLF001
                    request.tenant_id, conversation.id, expected=run_id
                )
                raise
            return None
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
            )
        )
    frame = {
        "type": "steer_queued",
        "run_id": active_run_id,
        "conversation_id": conversation.id,
        "message_id": message_id,
    }
    service._relay.publish(request.tenant_id, active_run_id, frame)  # noqa: SLF001
    return {**frame, "type": "queued"}


async def _persist_direct_input(
    service, request: TurnRequest, conversation_id: str, records, run_id: str
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
):
    if consumed_steer_id is not None:
        yield {
            "type": "steer_consumed",
            "run_id": run_id,
            "conversation_id": conversation.id,
            "message_id": consumed_steer_id,
        }
    yield {
        "type": "message_start",
        "run_id": run_id,
        "conversation_id": conversation.id,
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


async def _persist_assistant(service, request, conversation, run_id: str, collected) -> None:
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
        run_id = uuid.uuid4().hex
        steer = await service._next_pending_steer(  # noqa: SLF001
            request.tenant_id, conversation.id, run_id
        )
        if steer is None:
            service._clear_active_run(  # noqa: SLF001
                request.tenant_id,
                conversation.id,
                expected=current_run_id,
            )
            return None
        service._set_active_run(  # noqa: SLF001
            request.tenant_id, conversation.id, run_id
        )
    return run_id, steer


async def stream_turn(service, request: TurnRequest):
    records = validate_attachments(request.attachments, service._cfg)  # noqa: SLF001
    replay = await replay_if_duplicate(
        service._store,  # noqa: SLF001
        request.tenant_id,
        request.idempotency_key,
        request.conversation_id,
    )
    if replay is not None:
        for frame in replay:
            yield frame
        return
    conversation = await resolve_conversation(
        service._store,  # noqa: SLF001
        request.tenant_id,
        request.conversation_id,
        request.user_id,
        request.role,
        request.message,
    )
    run_id = uuid.uuid4().hex
    queued = await _reserve_or_queue(service, request, conversation, records, run_id)
    if queued is not None:
        yield queued
        return
    try:
        message, consumed_id = request.message, None
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
            ):
                yield event
            await _persist_assistant(service, request, conversation, run_id, collected)
            if any(event.get("type") == "cancelled" for event in collected):
                return
            next_turn = await _next_turn(service, request, conversation, run_id)
            if next_turn is None:
                return
            run_id, steer = next_turn
            message, records = steer.content or "", steer.attachments
            consumed_id = steer.id
    finally:
        async with service._lock_for(  # noqa: SLF001
            request.tenant_id, conversation.id
        ):
            service._clear_active_run(  # noqa: SLF001
                request.tenant_id,
                conversation.id,
                expected=run_id,
            )
