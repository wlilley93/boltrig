"""Owner-scoped conversation close, restore and rename routes."""

from __future__ import annotations

from fastapi import Request
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


async def _move_conversation(
    k, p, conversation_id: str, body: dict, audit, request: Request
) -> JSONResponse:
    """Move one human-owned conversation with ``move_conversation_workspace``.

    The CAS changes only project membership. It never changes the selected
    agent, message authorship, peer mail, or the active run's authority scope.
    """
    conversation = await k.store.get_conversation(p.tenant_id, conversation_id)
    if conversation is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if conversation.user_id != p.subject:
        return JSONResponse(
            {"status": "denied", "reason": "not your conversation"}, status_code=403
        )
    project_ids = _project_move_ids(body)
    if isinstance(project_ids, JSONResponse):
        return project_ids
    expected, target = project_ids
    if target is not None:
        visible = await k.store.list_workspaces_for_user(p.tenant_id, p.subject)
        workspace = next((item for item in visible if item.id == target), None)
        if workspace is None:
            return JSONResponse(
                {"status": "denied", "reason": "project is not available"},
                status_code=403,
            )
        if workspace.status != "active":
            return JSONResponse(
                {"status": "error", "reason": "project is archived"}, status_code=409
            )
    chat = getattr(request.app.state, "chat", None)
    if chat is not None:
        move = await chat.move_conversation_workspace_if_idle(
            p.tenant_id, conversation_id, expected, target
        )
        if move.busy:
            return JSONResponse(
                {"status": "error", "reason": "conversation_project_move_busy"},
                status_code=409,
            )
        found, converged = move.found, move.workspace_id
    else:
        found, converged = await k.store.move_conversation_workspace(
            p.tenant_id, conversation_id, expected, target
        )
    if not found:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if converged != target:
        return JSONResponse(
            {
                "status": "conflict",
                "reason": "conversation_project_changed",
                "workspace_id": converged,
            },
            status_code=409,
        )
    await audit(
        k,
        p,
        "data.conversation.project.move",
        {
            "conversation_id": conversation_id,
            "from_workspace_id": expected,
            "to_workspace_id": target,
        },
    )
    return JSONResponse({"status": "ok", "id": conversation_id, "workspace_id": target})


def _project_move_ids(body: dict) -> tuple[str | None, str | None] | JSONResponse:
    """Validate and normalize the explicit project-membership CAS pair."""
    if "expected_workspace_id" not in body:
        return JSONResponse(
            {"status": "error", "reason": "expected_workspace_id is required"},
            status_code=400,
        )
    expected = body.get("expected_workspace_id")
    target = body.get("workspace_id")
    if expected is not None and (
        not isinstance(expected, str) or not expected.strip() or len(expected) > 160
    ):
        return JSONResponse(
            {"status": "error", "reason": "expected_workspace_id is invalid"},
            status_code=400,
        )
    if target is not None and (
        not isinstance(target, str) or not target.strip() or len(target) > 160
    ):
        return JSONResponse(
            {"status": "error", "reason": "workspace_id is invalid"}, status_code=400
        )
    expected = expected.strip() if isinstance(expected, str) else None
    target = target.strip() if isinstance(target, str) else None
    return expected, target


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

    @app.patch("/v1/me/conversations/{conversation_id}/project")
    async def move_my_conversation(
        conversation_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _move_conversation(k, p, conversation_id, body, audit, request)
