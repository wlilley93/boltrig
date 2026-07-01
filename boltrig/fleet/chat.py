"""The conversational service (Round Two, Epic CONV).

A chat turn is handed to the fleet, streamed back as typed events, and persisted
as a conversation. Conversations are owner-scoped (SEC-25). Streaming rides the
kernel event relay keyed by the turn's run id, so a Pi run's tool/sub-agent/HITL
events surface in chat exactly as they happen (US-CONV-03/04) and a dropped
client can re-attach (US-CONV-07).

This lives in the fleet layer (it orchestrates the fleet); the kernel and models
import nothing from it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from boltrig.models import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    GrantSet,
    InvocationContext,
    MessageRole,
    BoltrigError,
    WorkItem,
    WorkStatus,
    utcnow,
)

from .continuity import compose_turn_task, continuity_enabled

# turn_executor(*, tenant_id, user_id, conversation_id, run_id, message, relay) -> awaitable.
# It publishes events to relay.publish(run_id, ...) during the run; ChatService
# closes the relay stream when it returns.
TurnExecutor = Callable[..., Awaitable[Any]]

_SCOPED_ROLES = {"org-admin", "compliance"}  # may read others' threads (SEC-25)


class ConversationForbidden(BoltrigError):
    status_code = 403
    reason = "conversation_forbidden"


def _can_read(conv: Conversation, user_id: str, role: str) -> bool:
    return conv.user_id == user_id or role in _SCOPED_ROLES


class ChatService:
    def __init__(self, store, relay, *, turn_executor: TurnExecutor | None = None) -> None:
        self._store = store
        self._relay = relay
        self._exec = turn_executor

    async def list_conversations(self, tenant_id: str, user_id: str) -> list[Conversation]:
        return await self._store.list_conversations(tenant_id, user_id)

    async def get_messages(
        self, tenant_id: str, user_id: str, role: str, conversation_id: str
    ) -> list[ConversationMessage] | None:
        conv = await self._store.get_conversation(tenant_id, conversation_id)
        if conv is None:
            return None
        if not _can_read(conv, user_id, role):
            raise ConversationForbidden("not permitted to read this conversation")
        return await self._store.list_messages(tenant_id, conversation_id)

    async def handle_turn(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str,
        message: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # RBAC before anything streams (SEC-25): continuing a thread requires access
        if conversation_id:
            conv = await self._store.get_conversation(tenant_id, conversation_id)
            if conv is None or not _can_read(conv, user_id, role):
                raise ConversationForbidden("no such conversation")
        else:
            conv = Conversation(
                id=uuid.uuid4().hex, tenant_id=tenant_id, user_id=user_id,
                title=(message[:60] or "New conversation"),
                status=ConversationStatus.ACTIVE,
            )
            await self._store.create_conversation(conv)

        run_id = uuid.uuid4().hex
        await self._store.add_message(
            ConversationMessage(
                id=uuid.uuid4().hex, conversation_id=conv.id, tenant_id=tenant_id,
                role=MessageRole.USER, content=message,
            )
        )
        yield {"type": "message_start", "run_id": run_id, "conversation_id": conv.id}

        collected: list[dict[str, Any]] = []
        async for event in self._drive(tenant_id, user_id, conv.id, run_id, message):
            collected.append(event)
            yield event

        yield {"type": "message_end", "run_id": run_id}

        text = "".join(e.get("delta", "") for e in collected if e.get("type") == "text_delta")
        hitl_id = next(
            (e.get("hitl_request_id") for e in collected if e.get("type") == "hitl"), None
        )
        await self._store.add_message(
            ConversationMessage(
                id=uuid.uuid4().hex, conversation_id=conv.id, tenant_id=tenant_id,
                role=MessageRole.ASSISTANT, content=text, run_id=run_id,
                hitl_request_id=hitl_id, events=collected,
            )
        )
        conv.updated_at = utcnow()
        await self._store.update_conversation(conv)

    async def _drive(self, tenant_id, user_id, conv_id, run_id, message):
        if self._exec is None:
            yield {"type": "text_delta", "delta": "(no runtime configured)"}
            return
        # run the turn concurrently; forward its relay events until the stream closes.
        task = asyncio.create_task(
            self._safe_exec(
                tenant_id=tenant_id, user_id=user_id, conversation_id=conv_id,
                run_id=run_id, message=message,
            )
        )
        try:
            async for event in self._relay.subscribe(run_id, replay=True):
                yield event
        finally:
            await task

    async def _safe_exec(self, **kw):
        run_id = kw["run_id"]
        try:
            await self._exec(relay=self._relay, **kw)
        except Exception as exc:  # a turn failure degrades, never crashes the stream (P9)
            self._relay.publish(run_id, {"type": "text_delta", "delta": f"(turn error: {type(exc).__name__})"})
        finally:
            self._relay.close(run_id)


def build_turn_executor(kernel, spawner, *, continuity: bool | None = None) -> TurnExecutor:
    """The production turn executor: normalise the turn to a work item linked by
    run id (US-CONV-02, kanban), route it through the fleet, and stream the
    result. Degrades to a plain reply when no capability can run it (P9).

    When continuity is on (the default, Round Six gap 3.1), the conversation's
    prior turns are composed into the task before the spawn so the turn carries
    its own context forward; the composition is deterministic + append-only
    (``continuity.compose_turn_task``) and reads only the caller's own
    tenant/conversation-scoped messages (SEC-27/SEC-49)."""
    use_continuity = continuity_enabled() if continuity is None else continuity

    async def executor(*, tenant_id, user_id, conversation_id, run_id, message, relay):
        perms = await kernel.store.get_tenant_permissions(tenant_id)
        item = WorkItem(
            id=run_id, tenant_id=tenant_id, source="chat", intent=message,
            confidence=1.0, convergent=False, status=WorkStatus.IN_FLIGHT,
            owner_member="chief-of-staff", hatchet_run_id=run_id, on_behalf_of=user_id,
        )
        await kernel.store.create_work_item(item)
        ctx = InvocationContext(
            tenant_id=tenant_id, grants=perms.grants, actor="chief-of-staff",
            actor_tier="tier1", run_id=run_id, on_behalf_of=user_id,
            extra={"conversation_id": conversation_id},
        )
        task = message
        if use_continuity:
            # The current user message was already persisted by handle_turn, so
            # this scoped read returns the full ordered transcript ending in it.
            history = await kernel.store.list_messages(tenant_id, conversation_id)
            task = compose_turn_task(history, message)
        try:
            result = await spawner.spawn(tenant_id, task, [], {}, ctx, partial_on_budget=True)
            summary = result.get("summary") or "Done."
            if result.get("degraded"):
                # Honesty about degradation (US-FLT-07): a degraded echo is never
                # presented as ordinary success - the reply carries the flag and a
                # visible prefix. WorkItem.degraded persists it (Beat 3); Beat 4's
                # pump stamps it from the spawn result on the claimed item.
                if not summary.startswith("degraded"):
                    summary = f"(degraded) {summary}"
                relay.publish(run_id, {"type": "text_delta", "delta": summary, "degraded": True})
            else:
                relay.publish(run_id, {"type": "text_delta", "delta": summary})
            item.status = WorkStatus.DONE
        except BoltrigError as exc:
            relay.publish(run_id, {"type": "text_delta", "delta": f"({exc.reason})"})
            item.status = WorkStatus.FAILED
        await kernel.store.update_work_item(item)

    return executor


def sse(event: dict[str, Any]) -> str:
    """Format one event as a Server-Sent Events frame."""
    return f"data: {json.dumps(event)}\n\n"


# keep GrantSet referenced for type clarity in the executor's context grants
_ = GrantSet
