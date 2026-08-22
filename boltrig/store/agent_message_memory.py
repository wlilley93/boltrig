"""In-memory immutable agent messages, deliveries, and session summaries."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

from boltrig.models import (
    AgentDelivery,
    AgentDeliveryStatus,
    AgentTurnLane,
    AgentTurnLease,
    ClaimedAgentMessage,
    utcnow,
)

from .agent_turn_memory import TURN_LANE_PRIORITY


class AgentMessageStoreMem:
    async def ensure_agent_session(self, session):
        key = (session.tenant_id, session.agent_address, session.conversation_id)
        with self._agent_mailbox_lock:
            existing = self._agent_sessions.get(key)
            if existing is None:
                self._agent_sessions[key] = session
                existing = session
        return replace(existing)

    async def get_agent_session(self, tenant_id, agent_address, conversation_id):
        row = self._agent_sessions.get((tenant_id, agent_address, conversation_id))
        return replace(row) if row is not None else None

    def _enqueue_agent_message_locked(self, message) -> bool:
        key = (message.tenant_id, message.id)
        if key in self._agent_messages:
            return False
        if (
            (message.tenant_id, message.sender) not in self._named_agents
            or (message.tenant_id, message.recipient) not in self._named_agents
        ):
            raise ValueError("agent message endpoints must be registered named agents")
        self._agent_messages[key] = message
        self._agent_deliveries[key] = AgentDelivery(
            tenant_id=message.tenant_id,
            message_id=message.id,
            recipient=message.recipient,
        )
        return True

    async def enqueue_agent_message(self, message):
        with self._agent_mailbox_lock:
            return self._enqueue_agent_message_locked(message)

    async def get_agent_message(self, tenant_id, message_id):
        row = self._agent_messages.get((tenant_id, message_id))
        return replace(row, authority=dict(row.authority)) if row is not None else None

    async def list_agent_conversation_messages(
        self, tenant_id, conversation_id, *, limit=500
    ):
        rows = [
            replace(row, authority=dict(row.authority))
            for (row_tenant, _), row in self._agent_messages.items()
            if row_tenant == tenant_id and row.conversation_id == conversation_id
        ]
        rows.sort(key=lambda row: (row.created_at, row.id))
        if limit is None:
            return rows
        return rows[: max(1, min(int(limit), 1000))]

    async def list_agent_inbox(self, tenant_id, recipient, *, limit=100):
        rows = []
        for key, message in self._agent_messages.items():
            if key[0] != tenant_id or message.recipient != recipient:
                continue
            delivery = self._agent_deliveries[key]
            rows.append(
                (replace(message, authority=dict(message.authority)), delivery.status.value)
            )
        rows.sort(key=lambda item: (item[0].created_at, item[0].id), reverse=True)
        return rows[: max(1, min(int(limit), 500))]

    def _expire_undeliverable_locked(self, tenant_id, now, max_attempts):
        for key, delivery in list(self._agent_deliveries.items()):
            message = self._agent_messages[key]
            recipient = self._named_agents.get((tenant_id, message.recipient))
            due = delivery.status == AgentDeliveryStatus.PENDING or (
                delivery.status == AgentDeliveryStatus.IN_FLIGHT
                and delivery.lease_expires_at is not None
                and delivery.lease_expires_at <= now
            )
            if key[0] == tenant_id and due and (
                recipient is None or not recipient.enabled
            ):
                self._agent_deliveries[key] = replace(
                    delivery,
                    status=AgentDeliveryStatus.FAILED,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error="named_agent_recipient_disabled",
                    updated_at=now,
                )
                continue
            if (
                key[0] == tenant_id
                and delivery.status == AgentDeliveryStatus.IN_FLIGHT
                and delivery.lease_expires_at is not None
                and delivery.lease_expires_at <= now
                and delivery.attempts >= max_attempts
            ):
                self._agent_deliveries[key] = replace(
                    delivery,
                    status=AgentDeliveryStatus.FAILED,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error="delivery_attempts_exhausted",
                    updated_at=now,
                )

    def _eligible_agent_deliveries_locked(self, tenant_id, now, max_attempts):
        eligible = []
        for key, message in self._agent_messages.items():
            if key[0] != tenant_id:
                continue
            delivery = self._agent_deliveries[key]
            due = (
                delivery.status == AgentDeliveryStatus.PENDING
                and (delivery.available_at is None or delivery.available_at <= now)
            ) or (
                delivery.status == AgentDeliveryStatus.IN_FLIGHT
                and delivery.lease_expires_at is not None
                and delivery.lease_expires_at <= now
            )
            if not due or delivery.attempts >= max_attempts:
                continue
            profile = self._named_agents.get((tenant_id, message.recipient))
            if profile is None or not profile.enabled:
                continue
            turn_key = (tenant_id, message.recipient)
            if self._agent_turn_leases.get(turn_key) is not None:
                continue
            interactive_waiting = any(
                row_tenant == tenant_id
                and row_address == message.recipient
                and TURN_LANE_PRIORITY[waiter[0]] < TURN_LANE_PRIORITY[AgentTurnLane.PEER]
                for (row_tenant, row_address, _), waiter
                in self._agent_turn_waiters.items()
            )
            if not interactive_waiting:
                eligible.append((message, delivery))
        return eligible

    async def claim_next_agent_message(
        self, tenant_id, worker_id, lease_seconds, *, max_attempts=3
    ):
        now = utcnow()
        lease_until = now + timedelta(seconds=max(1, int(lease_seconds)))
        with self._agent_mailbox_lock:
            self._prune_agent_turn_state_locked(now, tenant_id=tenant_id)
            self._expire_undeliverable_locked(tenant_id, now, max_attempts)
            eligible = self._eligible_agent_deliveries_locked(
                tenant_id, now, max_attempts
            )
            if not eligible:
                return None
            message, delivery = min(
                eligible, key=lambda item: (item[0].created_at, item[0].id)
            )
            claimed = replace(
                delivery,
                status=AgentDeliveryStatus.IN_FLIGHT,
                attempts=delivery.attempts + 1,
                lease_owner=worker_id,
                lease_expires_at=lease_until,
                available_at=None,
                updated_at=now,
            )
            self._agent_deliveries[(tenant_id, message.id)] = claimed
            turn_lease = AgentTurnLease(
                tenant_id=tenant_id,
                agent_address=message.recipient,
                owner=worker_id,
                token=f"atl_{uuid.uuid4().hex}",
                lane=AgentTurnLane.PEER,
                expires_at=lease_until,
            )
            self._agent_turn_leases[(tenant_id, message.recipient)] = turn_lease
            return ClaimedAgentMessage(
                message=replace(message, authority=dict(message.authority)),
                delivery=replace(claimed),
                turn_lease=turn_lease,
            )

    def _live_delivery_locked(self, tenant_id, message_id, turn_lease, now):
        delivery = self._agent_deliveries.get((tenant_id, message_id))
        if (
            delivery is None
            or delivery.status != AgentDeliveryStatus.IN_FLIGHT
            or delivery.lease_owner != turn_lease.owner
            or delivery.lease_expires_at is None
            or delivery.lease_expires_at <= now
        ):
            return None
        current = self._agent_turn_leases.get((tenant_id, delivery.recipient))
        if (
            current is None
            or current.owner != turn_lease.owner
            or current.token != turn_lease.token
            or current.lane is not AgentTurnLane.PEER
            or current.expires_at <= now
        ):
            return None
        return delivery

    async def complete_agent_message(
        self,
        tenant_id,
        message_id,
        turn_lease,
        *,
        reply=None,
        completed_at=None,
    ):
        now = completed_at or utcnow()
        with self._agent_mailbox_lock:
            delivery = self._live_delivery_locked(
                tenant_id, message_id, turn_lease, now
            )
            if delivery is None:
                return False
            if reply is not None:
                message = self._agent_messages[(tenant_id, message_id)]
                if (
                    reply.tenant_id != tenant_id
                    or reply.reply_to != message_id
                    or reply.sender != message.recipient
                    or reply.recipient != message.sender
                    or reply.conversation_id != message.conversation_id
                ):
                    raise ValueError("agent reply does not match the claimed message")
                self._enqueue_agent_message_locked(reply)
            self._agent_deliveries[(tenant_id, message_id)] = replace(
                delivery,
                status=AgentDeliveryStatus.DELIVERED,
                lease_owner=None,
                lease_expires_at=None,
                last_error=None,
                delivered_at=now,
                updated_at=now,
            )
            self._agent_turn_leases[(tenant_id, delivery.recipient)] = None
            return True

    async def fail_agent_message(
        self,
        tenant_id,
        message_id,
        turn_lease,
        error_code,
        *,
        retryable,
        max_attempts=3,
        backoff_seconds=2.0,
    ):
        now = utcnow()
        with self._agent_mailbox_lock:
            delivery = self._live_delivery_locked(
                tenant_id, message_id, turn_lease, now
            )
            if delivery is None:
                return False
            will_retry = bool(retryable and delivery.attempts < max_attempts)
            delay = max(0.0, float(backoff_seconds)) * min(
                64, 2 ** max(0, delivery.attempts - 1)
            )
            self._agent_deliveries[(tenant_id, message_id)] = replace(
                delivery,
                status=(
                    AgentDeliveryStatus.PENDING
                    if will_retry
                    else AgentDeliveryStatus.FAILED
                ),
                lease_owner=None,
                lease_expires_at=None,
                available_at=now + timedelta(seconds=delay) if will_retry else None,
                last_error=str(error_code or "delivery_failed")[:200],
                updated_at=now,
            )
            self._agent_turn_leases[(tenant_id, delivery.recipient)] = None
            return True

    async def renew_agent_message_claim(
        self, tenant_id, message_id, turn_lease, lease_seconds
    ):
        now = utcnow()
        with self._agent_mailbox_lock:
            delivery = self._live_delivery_locked(
                tenant_id, message_id, turn_lease, now
            )
            if delivery is None:
                return None
            renewed = replace(
                turn_lease,
                expires_at=now + timedelta(seconds=max(1, int(lease_seconds))),
            )
            self._agent_turn_leases[(tenant_id, delivery.recipient)] = renewed
            self._agent_deliveries[(tenant_id, message_id)] = replace(
                delivery,
                lease_expires_at=renewed.expires_at,
                updated_at=now,
            )
            return renewed

    async def add_agent_session_summary(self, summary):
        rows = self._agent_summaries.setdefault((summary.tenant_id, summary.session_id), [])
        if not any(row.id == summary.id for row in rows):
            rows.append(summary)

    async def get_latest_agent_session_summary(self, tenant_id, session_id):
        rows = self._agent_summaries.get((tenant_id, session_id), [])
        if not rows:
            return None
        return max(rows, key=lambda row: (row.covered_count, row.created_at))
