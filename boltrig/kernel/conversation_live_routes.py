"""Conversation detail and browser-safe live reattachment routes."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

_CURSOR_MAX = (1 << 63) - 1
_QUEUE_ID = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")
_QUEUE_MAX = 100


def _queue_order(value: Any) -> list[str] | None:
    if type(value) is not list or len(value) > _QUEUE_MAX:
        return None
    if any(type(item) is not str or _QUEUE_ID.fullmatch(item) is None for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return value


async def _reorder_queue(chat: Any, principal: Any, conversation_id: str, body: dict):
    expected = _queue_order(body.get("expected_message_ids"))
    ordered = _queue_order(body.get("message_ids"))
    if expected is None or ordered is None or set(expected) != set(ordered):
        return JSONResponse(
            {"status": "error", "reason": "queue_order_invalid"},
            status_code=400,
        )
    changed = await chat.reorder_pending_steers(
        principal.tenant_id,
        principal.subject,
        conversation_id,
        expected,
        ordered,
    )
    if not changed:
        return JSONResponse(
            {"status": "conflict", "reason": "queue_changed"},
            status_code=409,
        )
    return {"status": "ok", "message_ids": ordered}


def _register_queue_route(app: Any, principal: Any) -> None:
    @app.put("/v1/conversations/{conversation_id}/queue")
    async def reorder_conversation_queue(
        conversation_id: str, body: dict[str, Any], request: Request, p=principal
    ):
        chat = getattr(request.app.state, "chat", None)
        if chat is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        return await _reorder_queue(chat, p, conversation_id, body)


def _message_view(message: Any) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role.value,
        "content": message.content,
        "run_id": message.run_id,
        "recipient_agent_address": message.recipient_agent_address,
        "author_agent_address": message.author_agent_address,
        "hitl_request_id": message.hitl_request_id,
        "events": message.events,
        "attachments": message.attachments,
        "superseded_by": message.superseded_by,
        "created_at": message.created_at.isoformat(),
    }


async def _conversation_view(
    chat: Any, principal: Any, conversation_id: str
) -> dict[str, Any] | JSONResponse:
    conversation = await chat.get_conversation(
        principal.tenant_id, principal.subject, principal.role, conversation_id
    )
    if conversation is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    messages = await chat.get_messages(
        principal.tenant_id, principal.subject, principal.role, conversation_id
    )
    if messages is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    run_id = await chat.live_projection().active_run_for(
        principal.tenant_id, principal.subject, principal.role, conversation_id
    )
    model_context = await chat.context_compaction_view(
        principal.tenant_id, conversation_id, messages
    )
    queued_ids = await chat.pending_steer_ids(
        principal.tenant_id, principal.subject, principal.role, conversation_id
    )
    return {
        "conversation": {
            "id": conversation.id,
            "agent_address": conversation.agent_address,
            "workspace_id": conversation.workspace_id,
            "title": conversation.title,
            "status": conversation.status.value,
            "origin": conversation.origin.value,
            "source_ref": conversation.source_ref,
            "source_run_id": conversation.source_run_id,
            "companion_id": conversation.companion_id,
        },
        "messages": [_message_view(message) for message in messages],
        "active_run_id": run_id,
        "model_context": model_context,
        "queued_message_ids": queued_ids or [],
    }


async def _event_stream(
    projection: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    run_id: str,
    agent_address: str | None,
    cursor: int,
    replay_truncated: bool,
) -> AsyncIterator[str]:
    first: dict[str, Any] = {
        "cursor": cursor,
        "event": {
            "type": "message_start",
            "run_id": run_id,
            "conversation_id": conversation_id,
        },
    }
    if agent_address is not None:
        first["event"]["agent_address"] = agent_address
    if replay_truncated:
        first["replay_truncated"] = True
    yield f"data: {json.dumps(first)}\n\n"
    current = cursor
    async for seq, event in projection.follow(
        tenant_id, conversation_id, run_id, since=current
    ):
        current = seq
        yield f"data: {json.dumps({'cursor': current, 'event': event})}\n\n"
    end = {
        "cursor": current,
        "event": {"type": "message_end", "run_id": run_id},
    }
    yield f"data: {json.dumps(end)}\n\n"


def register_conversation_live_routes(app: Any, *, principal_dep: Any) -> None:
    principal = Depends(principal_dep)
    _register_queue_route(app, principal)

    @app.get("/v1/chat/config")
    async def chat_config(request: Request, p=principal):
        """Safe client preflight limits; enforcement remains in ChatService."""
        chat = getattr(request.app.state, "chat", None)
        if chat is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        return {"attachments": chat.public_attachment_config()}

    @app.get("/v1/conversations/{conversation_id}")
    async def conversation(conversation_id: str, request: Request, p=principal):
        chat = getattr(request.app.state, "chat", None)
        if chat is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        return await _conversation_view(chat, p, conversation_id)

    @app.get("/v1/conversations/{conversation_id}/events")
    async def conversation_events(
        conversation_id: str,
        request: Request,
        follow: int = 1,
        since: int | None = None,
        p=principal,
    ):
        chat = getattr(request.app.state, "chat", None)
        if chat is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        if follow != 1:
            return JSONResponse(
                {"status": "error", "reason": "follow must be 1"}, status_code=400
            )
        if since is not None and (since < 0 or since > _CURSOR_MAX):
            return JSONResponse(
                {"status": "error", "reason": "invalid cursor"}, status_code=400
            )
        projection = chat.live_projection()
        bound_conversation = await chat.get_conversation(
            p.tenant_id, p.subject, p.role, conversation_id
        )
        if bound_conversation is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        run_id = await projection.active_run_for(
            p.tenant_id, p.subject, p.role, conversation_id
        )
        if run_id is None:
            return JSONResponse(
                {"status": "idle", "conversation_id": conversation_id},
                status_code=409,
            )
        cursor, truncated = projection.replay_state(p.tenant_id, run_id, since)
        return StreamingResponse(
            _event_stream(
                projection,
                tenant_id=p.tenant_id,
                conversation_id=conversation_id,
                run_id=run_id,
                agent_address=bound_conversation.agent_address,
                cursor=cursor,
                replay_truncated=truncated,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )


def register_worker_query_routes(
    app: Any,
    *,
    principal_dep: Any,
    get_kernel: Any,
) -> None:
    """Compose live conversation reads with independently governed search."""
    register_conversation_live_routes(app, principal_dep=principal_dep)
    from .familiar_phenotype_routes import register_familiar_phenotype_routes
    from .federated_search_routes import register_federated_search_routes

    register_familiar_phenotype_routes(app, principal_dep=principal_dep)
    register_federated_search_routes(app, principal_dep, get_kernel)
