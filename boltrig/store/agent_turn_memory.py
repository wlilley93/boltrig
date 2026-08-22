"""In-memory named-agent registry and per-identity turn scheduler."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

from boltrig.models import AgentDeliveryStatus, AgentTurnLane, AgentTurnLease, utcnow

TURN_LANE_PRIORITY = {
    AgentTurnLane.INTERACTIVE: 0,
    AgentTurnLane.PEER: 10,
    AgentTurnLane.BACKGROUND: 20,
}


class AgentTurnStoreMem:
    async def upsert_named_agent(self, agent):
        now = utcnow()
        key = (agent.tenant_id, agent.address)
        with self._agent_mailbox_lock:
            existing = self._named_agents.get(key)
            if agent.default_for_intake:
                for other_key, other in list(self._named_agents.items()):
                    if other_key[0] == agent.tenant_id and other.address != agent.address:
                        self._named_agents[other_key] = replace(
                            other, default_for_intake=False, updated_at=now
                        )
            self._named_agents[key] = replace(
                agent,
                created_at=existing.created_at if existing is not None else agent.created_at,
                updated_at=now,
            )
            self._agent_turn_leases.setdefault(key, None)

    async def get_named_agent(self, tenant_id, address):
        row = self._named_agents.get((tenant_id, address))
        return replace(row) if row is not None else None

    async def list_named_agents(self, tenant_id, *, include_disabled=False):
        rows = [
            replace(row)
            for (row_tenant, _), row in self._named_agents.items()
            if row_tenant == tenant_id and (include_disabled or row.enabled)
        ]
        return sorted(rows, key=lambda row: row.address)

    async def deactivate_absent_named_agents(self, tenant_id, declared_addresses):
        declared = set(declared_addresses)
        now = utcnow()
        changed = []
        with self._agent_mailbox_lock:
            for key, row in list(self._named_agents.items()):
                if key[0] != tenant_id or row.address in declared or not row.enabled:
                    continue
                self._named_agents[key] = replace(
                    row, enabled=False, default_for_intake=False, updated_at=now
                )
                changed.append(row.address)
        return sorted(changed)

    def _prune_agent_turn_state_locked(self, now, *, tenant_id=None, address=None):
        for key, waiter in list(self._agent_turn_waiters.items()):
            if tenant_id is not None and key[0] != tenant_id:
                continue
            if address is not None and key[1] != address:
                continue
            if waiter[2] <= now:
                del self._agent_turn_waiters[key]
        for key, lease in list(self._agent_turn_leases.items()):
            if tenant_id is not None and key[0] != tenant_id:
                continue
            if address is not None and key[1] != address:
                continue
            if lease is not None and lease.expires_at <= now:
                self._agent_turn_leases[key] = None

    def _due_peer_message_locked(self, tenant_id, address, now):
        for key, message in self._agent_messages.items():
            if key[0] != tenant_id or message.recipient != address:
                continue
            delivery = self._agent_deliveries[key]
            if (
                delivery.status == AgentDeliveryStatus.PENDING
                and (delivery.available_at is None or delivery.available_at <= now)
            ) or (
                delivery.status == AgentDeliveryStatus.IN_FLIGHT
                and delivery.lease_expires_at is not None
                and delivery.lease_expires_at <= now
            ):
                return True
        return False

    async def acquire_agent_turn(
        self,
        tenant_id,
        agent_address,
        owner,
        lane,
        lease_seconds,
        *,
        waiter_ttl_seconds=600,
    ):
        """Join the per-identity queue and acquire its one distributed turn."""
        lane = AgentTurnLane(lane)
        now = utcnow()
        key = (tenant_id, agent_address)
        waiter_key = (*key, owner)
        with self._agent_mailbox_lock:
            profile = self._named_agents.get(key)
            if profile is None or not profile.enabled:
                raise ValueError("agent turn requires an enabled named agent")
            self._prune_agent_turn_state_locked(
                now, tenant_id=tenant_id, address=agent_address
            )
            current = self._agent_turn_leases.get(key)
            if current is not None and current.owner == owner:
                return current

            existing = self._agent_turn_waiters.get(waiter_key)
            requested_at = existing[1] if existing is not None else now
            self._agent_turn_waiters[waiter_key] = (
                lane,
                requested_at,
                now + timedelta(seconds=max(1, int(waiter_ttl_seconds))),
            )
            if current is not None:
                return None
            waiters = [
                (waiter_id, value)
                for (row_tenant, row_address, waiter_id), value
                in self._agent_turn_waiters.items()
                if row_tenant == tenant_id and row_address == agent_address
            ]
            selected_id, _ = min(
                waiters,
                key=lambda row: (
                    TURN_LANE_PRIORITY[row[1][0]],
                    row[1][1],
                    row[0],
                ),
            )
            if selected_id != owner:
                return None
            if (
                lane is AgentTurnLane.BACKGROUND
                and self._due_peer_message_locked(tenant_id, agent_address, now)
            ):
                return None

            lease = AgentTurnLease(
                tenant_id=tenant_id,
                agent_address=agent_address,
                owner=owner,
                token=f"atl_{uuid.uuid4().hex}",
                lane=lane,
                expires_at=now + timedelta(seconds=max(1, int(lease_seconds))),
            )
            self._agent_turn_leases[key] = lease
            del self._agent_turn_waiters[waiter_key]
            return lease

    async def renew_agent_turn(self, lease, lease_seconds):
        now = utcnow()
        key = (lease.tenant_id, lease.agent_address)
        with self._agent_mailbox_lock:
            current = self._agent_turn_leases.get(key)
            if (
                current is None
                or current.owner != lease.owner
                or current.token != lease.token
                or current.expires_at <= now
            ):
                return None
            renewed = replace(
                current,
                expires_at=now + timedelta(seconds=max(1, int(lease_seconds))),
            )
            self._agent_turn_leases[key] = renewed
            return renewed

    async def release_agent_turn(self, lease):
        key = (lease.tenant_id, lease.agent_address)
        with self._agent_mailbox_lock:
            current = self._agent_turn_leases.get(key)
            if (
                current is None
                or current.owner != lease.owner
                or current.token != lease.token
            ):
                return False
            self._agent_turn_leases[key] = None
            return True

    async def cancel_agent_turn_waiter(self, tenant_id, agent_address, owner):
        with self._agent_mailbox_lock:
            self._agent_turn_waiters.pop((tenant_id, agent_address, owner), None)
