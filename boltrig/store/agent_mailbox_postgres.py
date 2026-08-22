"""Composite PostgreSQL adapter for durable named-agent coordination."""

from __future__ import annotations

from .agent_delivery_claim_postgres import AgentDeliveryClaimStorePG
from .agent_delivery_settle_postgres import AgentDeliverySettleStorePG
from .agent_message_postgres import AgentMessageStorePG
from .agent_registry_postgres import AgentRegistryStorePG
from .agent_turn_postgres import AgentTurnStorePG


class AgentMailboxStorePG(
    AgentRegistryStorePG,
    AgentTurnStorePG,
    AgentMessageStorePG,
    AgentDeliveryClaimStorePG,
    AgentDeliverySettleStorePG,
):
    """One store surface composed from focused registry, turn, and delivery mixins."""


__all__ = ["AgentMailboxStorePG"]
