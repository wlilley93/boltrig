"""Composite in-memory adapter for named-agent turns and messages."""

from __future__ import annotations

from threading import Lock

from .agent_message_memory import AgentMessageStoreMem
from .agent_turn_memory import AgentTurnStoreMem


class AgentMailboxStoreMem(AgentTurnStoreMem, AgentMessageStoreMem):
    def _init_agent_mailbox_state(self) -> None:
        self._named_agents = {}
        self._agent_messages = {}
        self._agent_deliveries = {}
        self._agent_sessions = {}
        self._agent_summaries = {}
        self._agent_turn_leases = {}
        self._agent_turn_waiters = {}
        # Await never occurs while held, matching the durable adapter's row locks.
        self._agent_mailbox_lock = Lock()


__all__ = ["AgentMailboxStoreMem"]
