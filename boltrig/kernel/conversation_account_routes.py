"""Owner-scoped conversation close, restore and rename routes."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from boltrig.models import ConversationStatus, utcnow


async def _close_conversation(k, p, conversation_id: str, audit) -> JSONResponse:
    conversation = await k.store.get_conversation(p.tenant_id, conversation_id)
    if conversation is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if conversation.user_id != p.subject:
        return JSONResponse(
            {"status": "denied", "reason": "not your conversation"}, status_code=403
        )
    conversation.status = ConversationStatus.CLOSED
    conversation.updated_at = utcnow()
    await k.store.update_conversation(conversation)
    await audit(k, p, "data.conversation.delete", {"conversation_id": conversation_id})
    return JSONResponse({"status": "ok", "id": conversation_id})


async def _restore_conversation(k, p, conversation_id: str, audit) -> JSONResponse:
    found, owned, changed = await k.store.restore_closed_conversation(
        p.tenant_id, conversation_id, p.subject, utcnow()
    )
    if not found:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if not owned:
        return JSONResponse(
            {"status": "denied", "reason": "not your conversation"}, status_code=403
        )
    await audit(
        k,
        p,
        "data.conversation.restore",
        {"conversation_id": conversation_id, "changed": changed},
    )
    return JSONResponse(
        {
            "status": "ok",
            "id": conversation_id,
            "conversation_status": ConversationStatus.ACTIVE.value,
        }
    )


async def _rename_conversation(k, p, conversation_id: str, body: dict, audit) -> JSONResponse:
    conversation = await k.store.get_conversation(p.tenant_id, conversation_id)
    if conversation is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if conversation.user_id != p.subject:
        return JSONResponse(
            {"status": "denied", "reason": "not your conversation"}, status_code=403
        )
    title = body.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if not title or len(title) > 120:
        return JSONResponse(
            {"status": "error", "reason": "title must be 1-120 characters"},
            status_code=400,
        )
    conversation.title = title
    conversation.updated_at = utcnow()
    await k.store.update_conversation(conversation)
    await audit(
        k,
        p,
        "data.conversation.rename",
        {"conversation_id": conversation_id, "title_len": len(title)},
    )
    return JSONResponse({"status": "ok", "id": conversation_id})


def register_conversation_account_routes(app, P, K, audit) -> None:
    @app.delete("/v1/me/conversations/{conversation_id}")
    async def delete_my_conversation(conversation_id: str, k=K, p=P) -> JSONResponse:
        return await _close_conversation(k, p, conversation_id, audit)

    @app.post("/v1/me/conversations/{conversation_id}/restore")
    async def restore_my_conversation(conversation_id: str, k=K, p=P) -> JSONResponse:
        return await _restore_conversation(k, p, conversation_id, audit)

    @app.patch("/v1/me/conversations/{conversation_id}")
    async def rename_my_conversation(conversation_id: str, body: dict, k=K, p=P) -> JSONResponse:
        return await _rename_conversation(k, p, conversation_id, body, audit)
