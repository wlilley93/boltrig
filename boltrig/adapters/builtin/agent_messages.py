"""The governed ``agent.send`` peer-messaging verb."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import (
    AgentMessage,
    AgentMessageKind,
    InvocationContext,
    context_to_envelope,
)


def _message_id(context: InvocationContext, correlation_id: str | None) -> str:
    if correlation_id:
        material = (
            f"{context.tenant_id}\0{context.actor}\0{context.run_id or ''}\0"
            f"{correlation_id}"
        )
        return "am_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return "am_" + uuid.uuid4().hex


class AgentMessageAdapter:
    id = "agent-messages"
    version = "1.0.0"
    runtime = "script"

    def __init__(self, store: Any, *, events: Any = None) -> None:
        self._store = store
        self._events = events

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="agent.send",
                noun_id="agent",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "minLength": 1, "maxLength": 63},
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 32768,
                        },
                        "kind": {"type": "string", "enum": ["ask", "tell"]},
                        "conversation_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                        "correlation_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                    },
                    "required": ["to", "content", "kind"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "conversation_id": {"type": "string"},
                        "status": {"type": "string"},
                        "to": {"type": "string"},
                    },
                    "required": ["message_id", "conversation_id", "status", "to"],
                },
                consequence="low",
                description=(
                    "Send an ASK or TELL to another durable named tier-1 peer. "
                    "Delivery is asynchronous and serialized by recipient."
                ),
                idempotency_mode="disabled",
            )
        ]

    async def _resolve_endpoints(
        self, params: dict, context: InvocationContext
    ) -> tuple[Any, Any] | Result:
        """Sender + recipient checks, or the precise refusal.

        The caller never supplies ``from``. Identity comes only from the
        kernel-stamped context, and a mailbox row proves it is a durable peer.
        A missing ``to`` is INVALID, not NOT_FOUND: the NOT_FOUND class maps
        to the kernel-wide 'adapter_not_found' status, so an agent calling
        agent.send with a blank recipient surfaced as "the adapter does not
        exist" (measured on the beelink, 2026-08-21) - misdirecting diagnosis
        at the adapter registry instead of the call. NOT_FOUND stays reserved
        for a real address with no enabled peer, and names the address.
        """
        sender = await self._store.get_named_agent(context.tenant_id, context.actor)
        if context.actor_tier != "tier1" or sender is None or not sender.enabled:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "only a named tier-1 agent can send")
            )
        recipient_address = str(params.get("to") or "")
        if not recipient_address:
            return Result.failure(
                AdapterError(
                    ErrorClass.INVALID,
                    "agent.send requires 'to': the recipient's named-agent address",
                )
            )
        recipient = await self._store.get_named_agent(
            context.tenant_id, recipient_address
        )
        if recipient is None or not recipient.enabled:
            return Result.failure(
                AdapterError(
                    ErrorClass.NOT_FOUND,
                    f"no enabled named agent at '{recipient_address}'",
                )
            )
        if sender.address == recipient.address:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "agent messages require a peer recipient")
            )
        return sender, recipient

    async def execute(
        self,
        verb: str,
        params: dict,
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del credential
        if verb != "agent.send":
            return Result.failure(AdapterError(ErrorClass.INVALID, "unknown agent verb"))
        endpoints = await self._resolve_endpoints(params, context)
        if isinstance(endpoints, Result):
            return endpoints
        sender, recipient = endpoints
        try:
            kind = AgentMessageKind(str(params.get("kind") or ""))
        except ValueError:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "agent message kind must be ask or tell")
            )
        if kind is AgentMessageKind.REPLY:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "reply messages are system-created")
            )

        correlation_id = params.get("correlation_id")
        correlation_id = str(correlation_id) if correlation_id else None
        conversation_id = str(
            params.get("conversation_id") or ("ac_" + uuid.uuid4().hex)
        )
        message = AgentMessage(
            id=_message_id(context, correlation_id),
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            sender=sender.address,
            recipient=recipient.address,
            kind=kind,
            content=str(params.get("content") or ""),
            correlation_id=correlation_id,
            run_id=context.parent_run_id or context.run_id,
            authority=context_to_envelope(context),
        )
        inserted = await self._store.enqueue_agent_message(message)
        status = "queued" if inserted else "already_queued"
        self._publish(
            message,
            {
                "type": "agent_message_sent",
                "message_id": message.id,
                "conversation_id": message.conversation_id,
                "from": message.sender,
                "to": message.recipient,
                "kind": message.kind.value,
                "status": status,
            },
        )
        return Result.success(
            {
                "message_id": message.id,
                "conversation_id": message.conversation_id,
                "status": status,
                "to": message.recipient,
            }
        )

    def _publish(self, message: AgentMessage, event: dict[str, Any]) -> None:
        if self._events is None or not message.run_id:
            return
        try:
            self._events.publish(message.tenant_id, message.run_id, event)
        except Exception:
            pass

    async def health(self) -> str:
        return "ok"


def build(store: Any, *, events: Any = None) -> AgentMessageAdapter:
    return AgentMessageAdapter(store, events=events)


__all__ = ["AgentMessageAdapter", "build"]
