"""CAS next-agent and project projections for in-memory conversations."""

from __future__ import annotations


class ConversationBindingStoreMem:
    """Conversation CRUD with explicit compare-and-set routing changes."""

    def _init_conversation_binding_state(self) -> None:
        self._conversation_agent_bindings: dict[tuple[str, str], str | None] = {}
        self._conversation_workspace_bindings: dict[tuple[str, str], str | None] = {}

    async def create_conversation(self, conv):
        key = (conv.tenant_id, conv.id)
        if key not in self._convs:
            self._convs[key] = conv
            self._conversation_agent_bindings[key] = conv.agent_address
            self._conversation_workspace_bindings[key] = conv.workspace_id

    async def get_conversation(self, tenant_id, conv_id):
        return self._convs.get((tenant_id, conv_id))

    async def switch_conversation_agent(
        self, tenant_id, conv_id, expected_address, agent_address
    ):
        key = (tenant_id, conv_id)
        with self._conversation_lifecycle_lock:
            conv = self._convs.get(key)
            if conv is None:
                return None
            bound = self._conversation_agent_bindings.get(key)
            if bound == expected_address:
                bound = agent_address
                self._conversation_agent_bindings[key] = bound
                conv.agent_address = bound
            return bound

    async def move_conversation_workspace(
        self, tenant_id, conv_id, expected_workspace_id, workspace_id
    ):
        key = (tenant_id, conv_id)
        with self._conversation_lifecycle_lock:
            conv = self._convs.get(key)
            if conv is None:
                return False, None
            current = self._conversation_workspace_bindings.get(key)
            if current == expected_workspace_id:
                current = workspace_id
                self._conversation_workspace_bindings[key] = current
                conv.workspace_id = current
            return True, current

    async def update_conversation(self, conv):
        key = (conv.tenant_id, conv.id)
        bound = self._conversation_agent_bindings.get(key)
        workspace = self._conversation_workspace_bindings.get(key)
        if key in self._convs and conv.agent_address != bound:
            # Match PostgreSQL's metadata-only update: this path cannot reroute.
            conv.agent_address = bound
        if key in self._convs and conv.workspace_id != workspace:
            conv.workspace_id = workspace
        self._convs[key] = conv
        self._conversation_agent_bindings.setdefault(key, conv.agent_address)
        self._conversation_workspace_bindings.setdefault(key, conv.workspace_id)


__all__ = ["ConversationBindingStoreMem"]
