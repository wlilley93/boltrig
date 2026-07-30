"""Conversation detail and browser-safe live reattachment routes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

_CURSOR_MAX = (1 << 63) - 1


def _message_view(message: Any) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role.value,
        "content": message.content,
        "run_id": message.run_id,
        "hitl_request_id": message.hitl_request_id,
        "events": message.events,
        "attachments": message.attachments,
        "superseded_by": message.superseded_by,
        "created_at": message.created_at.isoformat(),
    }


async def _event_stream(
    projection: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    run_id: str,
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
        messages = await chat.get_messages(
            p.tenant_id, p.subject, p.role, conversation_id
        )
        if messages is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        run_id = await chat.live_projection().active_run_for(
            p.tenant_id, p.subject, p.role, conversation_id
        )
        model_context = await chat.context_compaction_view(
            p.tenant_id, conversation_id, messages
        )
        return {
            "messages": [_message_view(message) for message in messages],
            "active_run_id": run_id,
            "model_context": model_context,
        }

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
    from .federated_search_routes import register_federated_search_routes

    register_federated_search_routes(app, principal_dep, get_kernel)
