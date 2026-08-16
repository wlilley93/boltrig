"""The conversational service (Round Two, Epic CONV).

A chat turn is handed to the fleet, streamed back as typed events, and persisted
as a conversation. Conversations are owner-scoped (SEC-25). Streaming rides the
kernel relay keyed by tenant plus run id, so a Pi run's tool/sub-agent/HITL events
surface in chat exactly as they happen (US-CONV-03/04) and a dropped
client can re-attach (US-CONV-07).

This lives in the fleet layer (it orchestrates the fleet); the kernel and models
import nothing from it.

Mid-run steers (US-CHAT-15): a message posted to a conversation whose turn is in
flight never starts a parallel turn. Its content remains frozen in the append-only
message log while a separate, owner-reorderable scheduling projection chooses the
NEXT turn. ``ChatQueueService`` owns that reorder-and-claim boundary. A cancelled
turn never auto-consumes the queue (cancel wins).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from boltrig.config.manifest import ChatConfig
from boltrig.fleet.chat_attachments import (
    AttachmentRejected,
    attachment_task_supplement,
    validate_attachments as _validate_attachments,
)
from boltrig.fleet.chat_compaction import maybe_compact
from boltrig.fleet.chat_conversation_access import (
    ConversationClosed,
    ConversationForbidden,
    can_read_conversation as _can_read,
    resolve_conversation as _resolve_conversation,
)
from boltrig.fleet.chat_context_view import attachment_config, context_compaction
from boltrig.fleet.chat_regeneration import (
    RegenerateNotEligible,
    regeneration_inputs,
)
from boltrig.fleet.chat_queue import ChatQueueService
from boltrig.fleet.chat_stream_drive import drive_turn_events, safe_exec
from boltrig.fleet.chat_turn_execution import build_turn_executor
from boltrig.fleet.chat_turn_flow import TurnRequest, decision_request_id, stream_turn
from boltrig.models import (
    Conversation,
    ConversationMessage,
    GrantSet,
    MessageRole,
    utcnow,
)

__all__ = [
    "AttachmentRejected",
    "ChatService",
    "ConversationClosed",
    "ConversationForbidden",
    "RegenerateNotEligible",
    "_can_read",
    "_resolve_conversation",
    "_validate_attachments",
    "attachment_task_supplement",
    "build_turn_executor",
]

TurnExecutor = Callable[..., Awaitable[Any]]

# summariser(older_messages) -> awaitable[str]. An OPTIONAL model summariser for
# compaction; if wired it MUST run through the ONE kernel chokepoint (its output
# re-enters the task). On raise/empty the deterministic offline summariser stands in.
Summariser = Callable[[list[ConversationMessage]], Awaitable[str]]


class ChatService(ChatQueueService):
    def __init__(
        self,
        store,
        relay,
        *,
        turn_executor: TurnExecutor | None = None,
        chat_config: ChatConfig | None = None,
        summariser: Summariser | None = None,
        kernel=None,
    ) -> None:
        self._store = store
        self._relay = relay
        self._exec = turn_executor
        self._kernel = kernel
        self._cfg = chat_config if chat_config is not None else ChatConfig()
        # Optional model summariser for compaction; None => deterministic only.
        self._summariser = summariser

    def public_attachment_config(self) -> dict[str, Any]:
        """Return only caller-actionable intake limits and readability truth."""
        return attachment_config(self._cfg)

    def _lock_for(self, tenant_id: str, conversation_id: str):
        return self._relay.conversation_lock(tenant_id, conversation_id)

    def _active_run_for(self, tenant_id: str, conversation_id: str) -> str | None:
        return self._relay.active_run(tenant_id, conversation_id)

    def conversation_is_working(self, tenant_id: str, conversation_id: str) -> bool:
        """Project active-run truth without exposing the run identifier."""
        return self._active_run_for(tenant_id, conversation_id) is not None

    def _set_active_run(self, tenant_id: str, conversation_id: str, run_id: str) -> None:
        self._relay.set_active_run(tenant_id, conversation_id, run_id)

    def _clear_active_run(
        self,
        tenant_id: str,
        conversation_id: str,
        *,
        expected: str | None = None,
    ) -> bool:
        return self._relay.clear_active_run(tenant_id, conversation_id, expected=expected)

    def _refresh_active_run(
        self, tenant_id: str, conversation_id: str, *, expected: str
    ) -> bool:
        return self._relay.refresh_active_run(
            tenant_id, conversation_id, expected=expected
        )

    def live_projection(self):
        from boltrig.fleet.chat_live_projection import ChatLiveProjection

        return ChatLiveProjection(self)

    async def list_conversations(self, tenant_id: str, user_id: str) -> list[Conversation]:
        return await self._store.list_conversations(tenant_id, user_id)

    async def list_conversations_page(
        self, tenant_id: str, user_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[Conversation], int | None]:
        # Owner-scoped, bounded page (US-CONV-09). The page size is resolved against
        # ChatConfig here (config-as-data lives on the service): a caller-supplied
        # limit is clamped DOWN to the configured ceiling, None => the conservative
        # default. The unpaginated list_conversations stays untouched for callers who
        # do not opt in.
        size = self._cfg.resolve_page_size(limit)
        return await self._store.list_conversations_page(
            tenant_id, user_id, limit=size, offset=max(0, offset)
        )

    async def search_conversations(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[tuple[Conversation, str | None]], int | None]:
        # Owner-scoped search (US-CONV-10): scoping is the store's (tenant + this
        # user only), so a caller only ever sees their own conversations - never
        # another user's, even a scoped-read role. Same ChatConfig page ceiling as
        # the list.
        size = self._cfg.resolve_page_size(limit)
        return await self._store.search_conversations(
            tenant_id, user_id, query, limit=size, offset=max(0, offset)
        )

    async def get_messages(
        self, tenant_id: str, user_id: str, role: str, conversation_id: str
    ) -> list[ConversationMessage] | None:
        conv = await self._store.get_conversation(tenant_id, conversation_id)
        if conv is None:
            return None
        if not _can_read(conv, user_id, role):
            raise ConversationForbidden("not permitted to read this conversation")
        return await self._store.list_messages(tenant_id, conversation_id)

    async def get_conversation(
        self, tenant_id: str, user_id: str, role: str, conversation_id: str
    ) -> Conversation | None:
        conversation = await self._store.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            return None
        if not _can_read(conversation, user_id, role):
            raise ConversationForbidden("not permitted to read this conversation")
        return conversation

    async def context_compaction_view(
        self,
        tenant_id: str,
        conversation_id: str,
        messages: list[ConversationMessage],
    ) -> dict[str, Any]:
        """Describe the exact derived-summary boundary the next turn will use."""
        return await context_compaction(
            self._store, self._cfg, tenant_id, conversation_id, messages
        )

    async def handle_turn(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str,
        message: str,
        conversation_id: str | None = None,
        grants: GrantSet | None = None,
        attachments: list[dict[str, Any]] | None = None,
        workspace_id: str | None = None,
        scope: dict[str, Any] | None = None,
        on_behalf_bearer: str | None = None,
        idempotency_key: str | None = None,
        origin: str | None = None,
        model_profile_id: str | None = None, model_choice_id: str | None = None,
        input_role: MessageRole = MessageRole.USER,
    ) -> AsyncIterator[dict[str, Any]]:
        request = TurnRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            message=message,
            conversation_id=conversation_id,
            grants=grants,
            attachments=attachments,
            workspace_id=workspace_id,
            scope=scope,
            on_behalf_bearer=on_behalf_bearer,
            idempotency_key=idempotency_key,
            origin=origin,
            model_profile_id=model_profile_id,
            model_choice_id=model_choice_id,
            input_role=input_role,
        )
        async for event in stream_turn(self, request):
            yield event

    async def _maybe_compact(self, tenant_id: str, conversation_id: str) -> None:
        await maybe_compact(self, tenant_id, conversation_id)
    async def _drive(
        self,
        tenant_id,
        user_id,
        conv_id,
        run_id,
        message,
        role,
        grants,
        attachments=None,
        *,
        heartbeat=True,
        workspace_id=None,
        scope=None,
        on_behalf_bearer=None,
        origin=None,
        model_profile_id=None, model_choice_id=None,
    ):
        async for event in drive_turn_events(
            self,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conv_id,
            run_id=run_id,
            message=message,
            role=role,
            grants=grants,
            attachments=attachments,
            heartbeat=heartbeat,
            workspace_id=workspace_id,
            scope=scope,
            on_behalf_bearer=on_behalf_bearer,
            origin=origin,
            model_profile_id=model_profile_id,
            model_choice_id=model_choice_id,
        ):
            yield event

    async def regenerate_turn(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str,
        conversation_id: str,
        target_message_id: str,
        grants: GrantSet | None = None,
        workspace_id: str | None = None,
        scope: dict[str, Any] | None = None,
    ) -> tuple[ConversationMessage, str]:
        """Regenerate the last assistant reply (append-plus-supersede, [2026]
        VJS-COUNTY 4). Re-runs the last USER message on a NEW run id through the
        ordinary executor path, APPENDS a fresh assistant message (add_message stays
        insert-only - no forking, no in-place edit), and returns
        ``(new_message, superseded_id)``. The caller then writes the marker via
        ``store.mark_message_superseded`` (D2) and audits it (D7).

        Eligibility is bounded to the LAST assistant message (D6): ``target_message_id``
        must be the last non-superseded assistant reply, else ``RegenerateNotEligible``
        is raised BEFORE anything is re-run or persisted (fail-closed). Owner-only
        RBAC is enforced by the route, mirroring delete (D5)."""
        last_assistant, last_user = await regeneration_inputs(
            self._store,
            tenant_id,
            conversation_id,
            target_message_id,
        )

        # Re-run the last user turn on a NEW run id through the ordinary audited
        # executor path. The prior reply is still live at this point (the marker is
        # written AFTER, per D2), so the executor's continuity read composes it as
        # context; the append below is what makes this a fresh, separately-audited
        # run rather than a mutation of the frozen prior reply.
        run_id = uuid.uuid4().hex
        collected: list[dict[str, Any]] = []
        # Regenerate collects for persistence, it does not stream to a client, so
        # the transport keepalive is off - no heartbeat frames enter the record.
        async for event in self._drive(
            tenant_id,
            user_id,
            conversation_id,
            run_id,
            last_user.content or "",
            role,
            grants,
            last_user.attachments,
            heartbeat=False,
            workspace_id=workspace_id,
            scope=scope,
        ):
            collected.append(event)

        text = "".join(e.get("delta", "") for e in collected if e.get("type") == "text_delta")
        hitl_id = decision_request_id(collected)
        new_message = ConversationMessage(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role=MessageRole.ASSISTANT,
            content=text,
            run_id=run_id,
            hitl_request_id=hitl_id,
            events=collected,
        )
        await self._store.add_message(new_message)
        conv = await self._store.get_conversation(tenant_id, conversation_id)
        if conv is not None:
            conv.updated_at = utcnow()
            await self._store.update_conversation(conv)
        # A regenerate appends a reply too, so let compaction re-evaluate. The
        # superseded old reply is filtered out of the covered set (SEC exclusion).
        await self._maybe_compact(tenant_id, conversation_id)
        return new_message, last_assistant.id

    async def resume_held_write(
        self, tenant_id: str, run_id: str, hitl_request_id: str
    ) -> dict[str, Any]:
        """Carry out the write a human approved, on the turn that asked for it
        (decision 0018, Order 4).

        Sibling to ``regenerate_turn`` and deliberately unlike it: regenerate
        re-runs the MODEL, this re-runs the recorded CALL. A chat turn is
        synchronous and has already ended by the time a human approves, so
        nothing was left listening and an approved write was simply never made -
        the live defect this closes. The write happens BEFORE any model work and
        is never gated by it; narration carries no authority.
        """
        if self._kernel is None:
            return {"status": "skipped", "reason": "no_kernel"}
        from .held_write_resume import resume_held_write

        return await resume_held_write(
            self._kernel, self._store, self._relay, tenant_id, run_id, hitl_request_id
        )

    async def cancel(self, tenant_id: str, run_id: str) -> None:
        """End a live chat turn's SSE stream cleanly on a server-side cancel
        ([2026] VJS-COUNTY 6, D5).

        Cooperative, never a hard kill: this publishes a terminal ``cancelled``
        notice and closes the run's event stream, so a subscribed client stops
        waiting and the stream ends cleanly. The in-flight spawn is NEVER
        interrupted - it runs to completion and writes its work item; the durable
        cancel-request row (written by the owner-only audited route) is the record
        that persists and stops a restart resurrecting the run. Idempotent: a
        second close is a no-op (the executor's own finally also closes the relay)."""
        self._relay.publish(tenant_id, run_id, {"type": "cancelled", "run_id": run_id})
        self._relay.close(tenant_id, run_id)

    async def _safe_exec(self, **kw):
        await safe_exec(self, kw)
