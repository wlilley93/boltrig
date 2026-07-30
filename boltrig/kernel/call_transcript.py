"""Idempotent projection of final provider transcripts into chat history."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from boltrig.models import ConversationMessage, MessageRole, utcnow


async def project_call_transcript(kernel, call, event) -> None:
    payload = event.payload
    if (
        event.type != "transcript"
        or payload.get("final") is not True
        or payload.get("kind") not in {"input", "output"}
    ):
        return
    text = str(payload.get("text") or "").strip()
    if not text:
        return
    digest = hashlib.sha256(
        f"{event.tenant_id}:{event.call_id}:{event.id}".encode()
    ).hexdigest()
    await kernel.store.add_message(
        ConversationMessage(
            id=f"voice_{digest}",
            conversation_id=call.conversation_id,
            tenant_id=event.tenant_id,
            role=(
                MessageRole.USER
                if payload["kind"] == "input"
                else MessageRole.ASSISTANT
            ),
            content=text,
            run_id=call.run_id,
            # The normalized call event remains the one durable event record;
            # chat gets content only, avoiding duplicate event rendering.
            events=[],
            created_at=event.created_at,
        )
    )
    conversation = await kernel.store.get_conversation(
        event.tenant_id, call.conversation_id
    )
    if conversation is not None:
        await kernel.store.update_conversation(
            replace(conversation, updated_at=utcnow())
        )
