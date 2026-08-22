"""Persistence contract for flat, durable named-agent mailboxes."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models import (
    AgentMessage,
    AgentSession,
    AgentSessionSummary,
    AgentTurnLane,
    AgentTurnLease,
    ClaimedAgentMessage,
    NamedAgent,
)


class AgentMailboxStoreContract(Protocol):
    async def upsert_named_agent(self, agent: NamedAgent) -> None: ...
    async def get_named_agent(self, tenant_id: str, address: str) -> NamedAgent | None: ...
    async def list_named_agents(
        self, tenant_id: str, *, include_disabled: bool = False
    ) -> list[NamedAgent]: ...
    async def deactivate_absent_named_agents(
        self, tenant_id: str, declared_addresses: list[str]
    ) -> list[str]: ...

    async def acquire_agent_turn(
        self,
        tenant_id: str,
        agent_address: str,
        owner: str,
        lane: AgentTurnLane,
        lease_seconds: int,
        *,
        waiter_ttl_seconds: int = 600,
    ) -> AgentTurnLease | None: ...
    async def renew_agent_turn(
        self, lease: AgentTurnLease, lease_seconds: int
    ) -> AgentTurnLease | None: ...
    async def release_agent_turn(self, lease: AgentTurnLease) -> bool: ...
    async def cancel_agent_turn_waiter(
        self, tenant_id: str, agent_address: str, owner: str
    ) -> None: ...

    async def ensure_agent_session(self, session: AgentSession) -> AgentSession: ...
    async def get_agent_session(
        self, tenant_id: str, agent_address: str, conversation_id: str
    ) -> AgentSession | None: ...

    async def enqueue_agent_message(self, message: AgentMessage) -> bool: ...
    async def get_agent_message(
        self, tenant_id: str, message_id: str
    ) -> AgentMessage | None: ...
    async def list_agent_conversation_messages(
        self, tenant_id: str, conversation_id: str, *, limit: int | None = 500
    ) -> list[AgentMessage]: ...
    async def list_agent_inbox(
        self, tenant_id: str, recipient: str, *, limit: int = 100
    ) -> list[tuple[AgentMessage, str]]: ...

    async def claim_next_agent_message(
        self,
        tenant_id: str,
        worker_id: str,
        lease_seconds: int,
        *,
        max_attempts: int = 3,
    ) -> ClaimedAgentMessage | None: ...
    async def complete_agent_message(
        self,
        tenant_id: str,
        message_id: str,
        turn_lease: AgentTurnLease,
        *,
        reply: AgentMessage | None = None,
        completed_at: datetime | None = None,
    ) -> bool: ...
    async def fail_agent_message(
        self,
        tenant_id: str,
        message_id: str,
        turn_lease: AgentTurnLease,
        error_code: str,
        *,
        retryable: bool,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
    ) -> bool: ...
    async def renew_agent_message_claim(
        self,
        tenant_id: str,
        message_id: str,
        turn_lease: AgentTurnLease,
        lease_seconds: int,
    ) -> AgentTurnLease | None: ...

    async def add_agent_session_summary(self, summary: AgentSessionSummary) -> None: ...
    async def get_latest_agent_session_summary(
        self, tenant_id: str, session_id: str
    ) -> AgentSessionSummary | None: ...


__all__ = ["AgentMailboxStoreContract"]
