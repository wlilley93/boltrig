"""``AgentMailboxService`` serializes durable peer turns for flat named agents.

The model process is deliberately disposable. Identity, ordering, and
continuity live here: one mailbox lease per recipient, an immutable message
log, and append-only summaries over older turns. A named agent may delegate
bounded work to ephemeral children elsewhere, but an ephemeral never enters
this address registry or receives a mailbox.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from typing import Any, Mapping

from boltrig.models import (
    AgentMessage,
    AgentMessageKind,
    GrantSet,
    InvocationContext,
    context_from_envelope,
    context_to_envelope,
)
from .agent_mailbox_continuity import (
    AgentMailboxContinuity,
    DEFAULT_AGENT_COMPACTION_KEEP_RECENT,
    DEFAULT_AGENT_COMPACTION_THRESHOLD,
    agent_session_id,
    digest_id as _digest_id,
)
from .named_agent import agent_result_text

log = logging.getLogger("boltrig.fleet.agent_mailbox")

DEFAULT_AGENT_MESSAGE_ATTEMPTS = 3
DEFAULT_AGENT_MESSAGE_LEASE_SECONDS = 300
MAX_AGENT_REPLY_BYTES = 32 * 1024


class AgentMessageAuthorityError(ValueError):
    """A durable message does not carry a valid named-agent authority chain."""


def _bounded_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    marker = "\n[truncated]"
    room = max(0, limit - len(marker.encode("utf-8")))
    return encoded[:room].decode("utf-8", errors="ignore") + marker


class AgentMailboxService(AgentMailboxContinuity):
    """Claim and process at most one peer message per call."""

    def __init__(
        self,
        store: Any,
        agents: Mapping[str, Any],
        *,
        events: Any = None,
        worker_id: str | None = None,
        lease_seconds: int = DEFAULT_AGENT_MESSAGE_LEASE_SECONDS,
        max_attempts: int = DEFAULT_AGENT_MESSAGE_ATTEMPTS,
        compaction_threshold: int = DEFAULT_AGENT_COMPACTION_THRESHOLD,
        keep_recent: int = DEFAULT_AGENT_COMPACTION_KEEP_RECENT,
    ) -> None:
        if compaction_threshold < 0 or keep_recent < 0:
            raise ValueError("agent compaction limits cannot be negative")
        if compaction_threshold and keep_recent >= compaction_threshold:
            raise ValueError("agent keep_recent must be below the compaction threshold")
        self._store = store
        self._agents = dict(agents)
        self._events = events
        self.worker_id = worker_id or f"agent-mailbox-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = max(1, int(lease_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.compaction_threshold = int(compaction_threshold)
        self.keep_recent = int(keep_recent)

    async def run_once(self, tenant_id: str) -> bool:
        """Process one available mailbox turn; return whether one was claimed."""
        claimed = await self._store.claim_next_agent_message(
            tenant_id,
            self.worker_id,
            self.lease_seconds,
            max_attempts=self.max_attempts,
        )
        if claimed is None:
            return False
        await self._process_claimed(claimed)
        return True

    async def _process_claimed(self, claimed: Any) -> None:
        message = claimed.message
        lease_box = [claimed.turn_lease]
        heartbeat_stop = asyncio.Event()
        heartbeat_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_claim(
                message,
                lease_box,
                heartbeat_stop,
                heartbeat_lost,
            )
        )
        runner = self._agents.get(message.recipient)
        if runner is None:
            await self._stop_heartbeat(heartbeat, heartbeat_stop)
            await self._fail(
                message,
                lease_box[0],
                "named_agent_runtime_not_loaded",
                retryable=False,
            )
            return

        try:
            await self._deliver_claimed(
                message, lease_box, heartbeat, heartbeat_stop, heartbeat_lost, runner
            )
        except AgentMessageAuthorityError as exc:
            await self._stop_heartbeat(heartbeat, heartbeat_stop)
            await self._fail(
                message, lease_box[0], str(exc), retryable=False
            )
        except Exception as exc:  # mailbox faults retry; details remain server-side
            log.exception("named-agent mailbox turn failed for %s", message.id)
            await self._stop_heartbeat(heartbeat, heartbeat_stop)
            await self._fail(
                message,
                lease_box[0],
                f"named_agent_turn_exception:{type(exc).__name__}",
                retryable=True,
            )
        finally:
            await self._stop_heartbeat(heartbeat, heartbeat_stop)

    async def _deliver_claimed(
        self, message, lease_box, heartbeat, heartbeat_stop, heartbeat_lost, runner
    ) -> None:
        context = self._delivery_context(message)
        continuity = await self._continuity(message)
        self._publish(
            message,
            {
                "type": "agent_message_received",
                "message_id": message.id,
                "conversation_id": message.conversation_id,
                "from": message.sender,
                "to": message.recipient,
                "kind": message.kind.value,
            },
        )
        result = await runner.respond(message, continuity, context)
        if not result.ok or result.degraded:
            reason = result.degrade_reason or "named_agent_turn_failed"
            await self._stop_heartbeat(heartbeat, heartbeat_stop)
            await self._fail(message, lease_box[0], reason, retryable=True)
            return

        reply = None
        if message.kind is AgentMessageKind.ASK:
            answer = agent_result_text(result)
            if not answer:
                await self._stop_heartbeat(heartbeat, heartbeat_stop)
                await self._fail(
                    message,
                    lease_box[0],
                    "named_agent_empty_reply",
                    retryable=True,
                )
                return
            reply = self._reply(message, answer, context)

        await self._stop_heartbeat(heartbeat, heartbeat_stop)
        if heartbeat_lost.is_set():
            return
        committed = await self._store.complete_agent_message(
            message.tenant_id,
            message.id,
            lease_box[0],
            reply=reply,
        )
        if not committed:
            return  # the lease fence won; discard this stale worker's result
        self._publish(
            message,
            {
                "type": "agent_message_delivered",
                "message_id": message.id,
                "conversation_id": message.conversation_id,
                "from": message.sender,
                "to": message.recipient,
                "kind": message.kind.value,
            },
        )
        if reply is not None:
            self._publish(
                message,
                {
                    "type": "agent_message_reply",
                    "message_id": reply.id,
                    "reply_to": message.id,
                    "conversation_id": reply.conversation_id,
                    "from": reply.sender,
                    "to": reply.recipient,
                    "content": reply.content,
                },
            )
        await self._compact(message)

    async def _heartbeat_claim(
        self, message, lease_box, stop: asyncio.Event, lost: asyncio.Event
    ) -> None:
        interval = max(1.0, min(30.0, self.lease_seconds / 3))
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                try:
                    renewed = await self._store.renew_agent_message_claim(
                        message.tenant_id,
                        message.id,
                        lease_box[0],
                        self.lease_seconds,
                    )
                except Exception:
                    log.exception(
                        "named-agent turn heartbeat failed for %s", message.id
                    )
                    lost.set()
                    return
                if renewed is None:
                    lost.set()
                    return
                lease_box[0] = renewed

    @staticmethod
    async def _stop_heartbeat(task: asyncio.Task, stop: asyncio.Event) -> None:
        if task.done():
            await task
            return
        stop.set()
        await task

    def _delivery_context(self, message: AgentMessage) -> InvocationContext:
        try:
            source = context_from_envelope(dict(message.authority))
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentMessageAuthorityError("agent_message_authority_invalid") from exc
        if source.tenant_id != message.tenant_id:
            raise AgentMessageAuthorityError("agent_message_tenant_mismatch")
        if source.actor != message.sender or source.actor_tier != "tier1":
            raise AgentMessageAuthorityError("agent_message_sender_not_tier1")

        # Peer coordination is an intrinsic named-agent operation. It is added
        # only after proving the durable sender was tier-1; explicit denies still
        # dominate, and the independent tenant ceiling still binds dispatch.
        grants = GrantSet.of(
            list(source.grants.allow) + ["agent.send"],
            list(source.grants.deny) + ["chat.present"],
        )
        parent = message.run_id or source.parent_run_id or source.run_id
        return replace(
            source,
            run_id=_digest_id("amt_", message.tenant_id, message.id, message.recipient),
            parent_run_id=parent,
            grants=grants,
            actor=message.recipient,
            actor_tier="tier1",
            extra={
                **source.extra,
                "conversation_id": message.conversation_id,
                "agent_conversation_id": message.conversation_id,
                "named_agent_address": message.recipient,
            },
        )

    def _reply(
        self,
        message: AgentMessage,
        answer: str,
        context: InvocationContext,
    ) -> AgentMessage:
        return AgentMessage(
            id=_digest_id("amr_", message.tenant_id, message.id),
            tenant_id=message.tenant_id,
            conversation_id=message.conversation_id,
            sender=message.recipient,
            recipient=message.sender,
            kind=AgentMessageKind.REPLY,
            content=_bounded_utf8(answer, MAX_AGENT_REPLY_BYTES),
            reply_to=message.id,
            correlation_id=message.correlation_id,
            run_id=message.run_id,
            authority=context_to_envelope(context),
        )

    async def _fail(
        self, message: AgentMessage, turn_lease, error_code: str, *, retryable: bool
    ) -> None:
        changed = await self._store.fail_agent_message(
            message.tenant_id,
            message.id,
            turn_lease,
            error_code,
            retryable=retryable,
            max_attempts=self.max_attempts,
        )
        if changed:
            self._publish(
                message,
                {
                    "type": "agent_message_failed",
                    "message_id": message.id,
                    "conversation_id": message.conversation_id,
                    "from": message.sender,
                    "to": message.recipient,
                    "reason": error_code[:200],
                    "retryable": retryable,
                },
            )

    def _publish(self, message: AgentMessage, event: dict[str, Any]) -> None:
        if self._events is None or not message.run_id:
            return
        try:
            self._events.publish(message.tenant_id, message.run_id, event)
        except Exception:  # observability never changes delivery outcome
            pass


__all__ = [
    "AgentMailboxService",
    "AgentMessageAuthorityError",
    "DEFAULT_AGENT_COMPACTION_KEEP_RECENT",
    "DEFAULT_AGENT_COMPACTION_THRESHOLD",
    "DEFAULT_AGENT_MESSAGE_ATTEMPTS",
    "DEFAULT_AGENT_MESSAGE_LEASE_SECONDS",
    "agent_session_id",
]
