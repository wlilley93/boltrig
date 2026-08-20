"""Immutable named-agent binding for the in-memory conversation store."""

from __future__ import annotations


class ConversationBindingStoreMem:
    """Conversation CRUD whose routing key may only move from NULL once."""

    def _init_conversation_binding_state(self) -> None:
        self._conversation_agent_bindings: dict[tuple[str, str], str | None] = {}

    async def create_conversation(self, conv):
        key = (conv.tenant_id, conv.id)
        if key not in self._convs:
            self._convs[key] = conv
            self._conversation_agent_bindings[key] = conv.agent_address

    async def get_conversation(self, tenant_id, conv_id):
        return self._convs.get((tenant_id, conv_id))

    async def bind_conversation_agent(self, tenant_id, conv_id, agent_address):
        key = (tenant_id, conv_id)
        with self._conversation_lifecycle_lock:
            conv = self._convs.get(key)
            if conv is None:
                return None
            bound = self._conversation_agent_bindings.get(key)
            if bound is None:
                bound = agent_address
                self._conversation_agent_bindings[key] = bound
                conv.agent_address = bound
            return bound

    async def update_conversation(self, conv):
        key = (conv.tenant_id, conv.id)
        bound = self._conversation_agent_bindings.get(key)
        if key in self._convs and conv.agent_address != bound:
            # Match PostgreSQL's metadata-only update: this path cannot rebind.
            conv.agent_address = bound
        self._convs[key] = conv
        self._conversation_agent_bindings.setdefault(key, conv.agent_address)


__all__ = ["ConversationBindingStoreMem"]
