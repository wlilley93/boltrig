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
import base64
import binascii
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from boltrig.config.manifest import ChatConfig
from boltrig.models import (
    EMPTY_GRANTS,
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
from .prompt_stack import wrap_untrusted
from .pump import persist_new_work_items

# turn_executor(*, tenant_id, user_id, role, grants, conversation_id, run_id,
# message, attachments, relay) -> awaitable. It publishes events to
# relay.publish(run_id, ...) during the run; ChatService closes the relay stream
# when it returns.
TurnExecutor = Callable[..., Awaitable[Any]]

_SCOPED_ROLES = {"org-admin", "compliance"}  # may read others' threads (SEC-25)


class ConversationForbidden(BoltrigError):
    status_code = 403
    reason = "conversation_forbidden"


class AttachmentRejected(BoltrigError):
    """A chat turn's attachments breached the ChatConfig caps ([2026] VJS-COUNTY 3).

    The whole turn is refused at intake before anything is persisted or streamed;
    over-cap input is never truncated to fit."""

    status_code = 413
    reason = "attachment_rejected"


class RegenerateNotEligible(BoltrigError):
    """Regenerate was asked of a message that is not the last assistant reply, or a
    conversation with no reply to regenerate ([2026] VJS-COUNTY 4, D6)."""

    status_code = 409
    reason = "regenerate_not_eligible"


def _can_read(conv: Conversation, user_id: str, role: str) -> bool:
    return conv.user_id == user_id or role in _SCOPED_ROLES


def _is_text_attachment(media_type: str) -> bool:
    """Only a ``text/*`` attachment is agent-readable and gets enveloped into the
    task ([2026] VJS-COUNTY 3, D4). Every other media type is persisted record-only
    and is NEVER decoded into the model input."""
    return (media_type or "").lower().startswith("text/")


def _validate_attachments(
    attachments: list[dict[str, Any]] | None, cfg: ChatConfig
) -> list[dict[str, Any]]:
    """Enforce the attachment caps on DECODED bytes and count at chat intake
    ([2026] VJS-COUNTY 3, D3), returning the normalised record list to persist.

    The whole turn is rejected (nothing persisted, nothing streamed) the moment a
    cap is breached; over-cap input is never truncated. Caps come only from the
    typed ``ChatConfig`` (never call-site constants)."""
    if not attachments:
        return []
    if not isinstance(attachments, list):
        raise AttachmentRejected("attachments must be a list")
    if len(attachments) > cfg.max_attachments:
        raise AttachmentRejected(
            f"too many attachments (max {cfg.max_attachments})"
        )
    total = 0
    records: list[dict[str, Any]] = []
    for raw in attachments:
        if not isinstance(raw, dict):
            raise AttachmentRejected("each attachment must be an object")
        name = str(raw.get("name") or "attachment")
        media_type = str(raw.get("media_type") or "application/octet-stream")
        data = raw.get("data") or ""
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AttachmentRejected("attachment data is not valid base64") from exc
        size = len(decoded)
        if size > cfg.max_attachment_bytes:
            raise AttachmentRejected(
                f"attachment {name!r} is {size} bytes "
                f"(max {cfg.max_attachment_bytes} decoded)"
            )
        total += size
        if total > cfg.max_total_attachment_bytes:
            raise AttachmentRejected(
                f"attachments total {total} bytes "
                f"(max {cfg.max_total_attachment_bytes} decoded)"
            )
        # Record-only persistence: the base64 blob plus metadata. Whether it is
        # decoded into the task later is decided at composition time by media type.
        records.append(
            {"name": name, "media_type": media_type, "data": str(data), "size": size}
        )
    return records


def attachment_task_supplement(attachments: list[dict[str, Any]] | None) -> str:
    """Compose the model-visible supplement for a turn's attachments ([2026]
    VJS-COUNTY 3, D4). ONLY ``text/*`` attachments are decoded, and each is wrapped
    in a typed ``wrap_untrusted(kind="attachment")`` envelope so its bytes are DATA,
    never instructions (M1 / SEC-72). Every non-text attachment is skipped here, so
    its content never reaches the task or the model. Returns an empty string when no
    text attachment is present, so the bare/continuity task is unchanged."""
    parts: list[str] = []
    for att in attachments or []:
        if not _is_text_attachment(str(att.get("media_type", ""))):
            continue  # record-only; never decoded into the task
        try:
            text = base64.b64decode(att.get("data") or "", validate=True).decode(
                "utf-8", "replace"
            )
        except (binascii.Error, ValueError):
            continue
        parts.append(
            wrap_untrusted("attachment", str(att.get("name") or "attachment"), text)
        )
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts)


class ChatService:
    def __init__(
        self,
        store,
        relay,
        *,
        turn_executor: TurnExecutor | None = None,
        chat_config: ChatConfig | None = None,
    ) -> None:
        self._store = store
        self._relay = relay
        self._exec = turn_executor
        # The attachment caps live on ChatConfig ([2026] VJS-COUNTY 3); absent a
        # manifest the fail-closed defaults (conservative, non-zero) apply.
        self._cfg = chat_config if chat_config is not None else ChatConfig()

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
        grants: GrantSet | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # Enforce the attachment caps FIRST ([2026] VJS-COUNTY 3, D3): an over-cap
        # turn is refused whole before ANY side effect - before a new conversation is
        # created, before add_message, and before any stream yield - so nothing is
        # persisted and over-cap input is never truncated to fit.
        records = _validate_attachments(attachments, self._cfg)

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
                role=MessageRole.USER, content=message, attachments=records,
            )
        )
        yield {"type": "message_start", "run_id": run_id, "conversation_id": conv.id}

        collected: list[dict[str, Any]] = []
        async for event in self._drive(
            tenant_id, user_id, conv.id, run_id, message, role, grants, records
        ):
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

    async def _drive(
        self, tenant_id, user_id, conv_id, run_id, message, role, grants,
        attachments=None,
    ):
        if self._exec is None:
            yield {"type": "text_delta", "delta": "(no runtime configured)"}
            return
        # run the turn concurrently; forward its relay events until the stream closes.
        task = asyncio.create_task(
            self._safe_exec(
                tenant_id=tenant_id, user_id=user_id, conversation_id=conv_id,
                run_id=run_id, message=message, role=role, grants=grants,
                attachments=attachments or [],
            )
        )
        try:
            async for event in self._relay.subscribe(run_id, replay=True):
                yield event
        finally:
            await task

    async def regenerate_turn(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str,
        conversation_id: str,
        target_message_id: str,
        grants: GrantSet | None = None,
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
        messages = await self._store.list_messages(tenant_id, conversation_id)
        live = [m for m in messages if m.superseded_by is None]
        last_assistant = next(
            (m for m in reversed(live) if m.role == MessageRole.ASSISTANT), None
        )
        if last_assistant is None or last_assistant.id != target_message_id:
            raise RegenerateNotEligible(
                "only the last assistant message may be regenerated"
            )
        last_user = next(
            (m for m in reversed(live) if m.role == MessageRole.USER), None
        )
        if last_user is None:
            raise RegenerateNotEligible("no user message to regenerate")

        # Re-run the last user turn on a NEW run id through the ordinary audited
        # executor path. The prior reply is still live at this point (the marker is
        # written AFTER, per D2), so the executor's continuity read composes it as
        # context; the append below is what makes this a fresh, separately-audited
        # run rather than a mutation of the frozen prior reply.
        run_id = uuid.uuid4().hex
        collected: list[dict[str, Any]] = []
        async for event in self._drive(
            tenant_id, user_id, conversation_id, run_id,
            last_user.content or "", role, grants, last_user.attachments,
        ):
            collected.append(event)

        text = "".join(
            e.get("delta", "") for e in collected if e.get("type") == "text_delta"
        )
        hitl_id = next(
            (e.get("hitl_request_id") for e in collected if e.get("type") == "hitl"),
            None,
        )
        new_message = ConversationMessage(
            id=uuid.uuid4().hex, conversation_id=conversation_id, tenant_id=tenant_id,
            role=MessageRole.ASSISTANT, content=text, run_id=run_id,
            hitl_request_id=hitl_id, events=collected,
        )
        await self._store.add_message(new_message)
        conv = await self._store.get_conversation(tenant_id, conversation_id)
        if conv is not None:
            conv.updated_at = utcnow()
            await self._store.update_conversation(conv)
        return new_message, last_assistant.id

    async def cancel(self, run_id: str) -> None:
        """End a live chat turn's SSE stream cleanly on a server-side cancel
        ([2026] VJS-COUNTY 6, D5).

        Cooperative, never a hard kill: this publishes a terminal ``cancelled``
        notice and closes the run's event stream, so a subscribed client stops
        waiting and the stream ends cleanly. The in-flight spawn is NEVER
        interrupted - it runs to completion and writes its work item; the durable
        cancel-request row (written by the owner-only audited route) is the record
        that persists and stops a restart resurrecting the run. Idempotent: a
        second close is a no-op (the executor's own finally also closes the relay)."""
        self._relay.publish(run_id, {"type": "cancelled", "run_id": run_id})
        self._relay.close(run_id)

    async def _safe_exec(self, **kw):
        run_id = kw["run_id"]
        try:
            await self._exec(relay=self._relay, **kw)
        except Exception as exc:  # a turn failure degrades, never crashes the stream (P9)
            self._relay.publish(run_id, {"type": "text_delta", "delta": f"(turn error: {type(exc).__name__})"})
        finally:
            self._relay.close(run_id)


def build_turn_executor(
    kernel,
    spawner,
    *,
    continuity: bool | None = None,
    chat_config: ChatConfig | None = None,
) -> TurnExecutor:
    """The production turn executor: normalise the turn to a work item linked by
    run id (US-CONV-02, kanban), route it through the fleet, and stream the
    result. Degrades to a plain reply when no capability can run it (P9).

    When continuity is on (the default, Round Six gap 3.1), the conversation's
    prior turns are composed into the task before the spawn so the turn carries
    its own context forward; the composition is deterministic + append-only
    (``continuity.compose_turn_task``) and reads only the caller's own
    tenant/conversation-scoped messages (SEC-27/SEC-49).

    ``chat_config`` is the manifest ``chat`` knob deciding which skill set a
    bare turn spawns with per caller role; absent a manifest it defaults to the
    fail-closed ``ChatConfig()`` (no skills for any role)."""
    use_continuity = continuity_enabled() if continuity is None else continuity
    chat_cfg = chat_config if chat_config is not None else ChatConfig()

    async def executor(*, tenant_id, user_id, role, grants, conversation_id,
                       run_id, message, relay, attachments=None):
        perms = await kernel.store.get_tenant_permissions(tenant_id)
        # Bare-turn authority is manifest data under a caller ceiling
        # ([2026] VJS-COUNTY 1): the chat.skills_by_role knob selects the turn's
        # skill set for the caller's role (default_skills when unmapped), and a
        # manifest entry naming a missing skill is skipped, never escalated, so
        # the knob can only reduce authority (fail-closed).
        turn_skills: list[str] = []
        for skill_id in chat_cfg.skills_by_role.get(role, chat_cfg.default_skills):
            if await kernel.store.get_skill(tenant_id, skill_id) is not None:
                turn_skills.append(skill_id)
        # Every chat spawn is ceilinged by the caller's role-resolved grants
        # (the Principal's, resolved via identity/rbac.py); a caller whose role
        # resolution failed carries the empty set (SEC-78).
        ceiling = grants if grants is not None else EMPTY_GRANTS
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
        # The inbound turn text is untrusted user/channel input, so it is enveloped
        # before it reaches the model (M1 / SEC-72). On the continuity path the
        # transcript renderer envelopes every turn body (continuity._render_message);
        # on the bare path we wrap the single message here so neither path ever feeds
        # raw inbound text into the prompt.
        task = wrap_untrusted("channel_inbound", user_id or "user", message)
        if use_continuity:
            # The current user message was already persisted by handle_turn, so
            # this scoped read returns the full ordered transcript ending in it.
            # compose_turn_task FILTERS superseded messages ([2026] VJS-COUNTY 4,
            # D4), so a regenerated-away reply never re-enters continuity.
            history = await kernel.store.list_messages(tenant_id, conversation_id)
            task = compose_turn_task(history, message)
        # Attachments reach the model only as data ([2026] VJS-COUNTY 3, D4): text
        # attachments are enveloped via wrap_untrusted(kind=attachment) and appended;
        # every non-text attachment is skipped here, never decoded into the task.
        task += attachment_task_supplement(attachments)
        try:
            result = await spawner.spawn(
                tenant_id, task, turn_skills, {}, ctx,
                partial_on_budget=True, grant_ceiling=ceiling,
            )
            summary = result.get("summary") or "Done."
            # Honesty about degradation (US-FLT-07): the flag persists on the
            # turn's work item, and a degraded echo is never presented as
            # ordinary success - the reply carries the flag and a visible prefix.
            item.degraded = bool(result.get("degraded"))
            if item.degraded:
                if not summary.startswith("degraded"):
                    summary = f"(degraded) {summary}"
                relay.publish(run_id, {"type": "text_delta", "delta": summary, "degraded": True})
            else:
                relay.publish(run_id, {"type": "text_delta", "delta": summary})
            # Two-lane hand-off (D5/D7): the turn itself rode the direct-spawn
            # fast lane; its discovered follow-on work is filed as PENDING
            # children (owner/department unset) so the org lane pumps it onward.
            await persist_new_work_items(
                kernel.store, item, result.get("new_work_items"), source="chat"
            )
            item.status = WorkStatus.DONE
        except BoltrigError as exc:
            relay.publish(run_id, {"type": "text_delta", "delta": f"({exc.reason})"})
            item.status = WorkStatus.FAILED
        await kernel.store.update_work_item(item)

    return executor
