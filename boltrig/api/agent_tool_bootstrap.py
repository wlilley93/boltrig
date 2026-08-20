"""Register the always-available, policy-scoped agent support tools."""

from __future__ import annotations

import logging

from boltrig.kernel import Kernel
from boltrig.kernel.work_read_adapter import build_work_read_adapter
from boltrig.models import NamedAgent
from boltrig.skills.shelf import build_skill_shelf_adapter

log = logging.getLogger("boltrig.bootstrap")


async def register_agent_support(kernel: Kernel, tenant_id: str) -> None:
    """Register the tools and durable identity substrate every agent uses."""

    from boltrig.adapters.builtin.agent_messages import build as build_agent_messages

    await kernel.register_adapter(tenant_id, build_skill_shelf_adapter(kernel.store))
    await kernel.register_adapter(tenant_id, build_work_read_adapter(kernel.store))
    await kernel.register_adapter(
        tenant_id, build_agent_messages(kernel.store, events=kernel.events)
    )
    if not await kernel.store.list_named_agents(tenant_id):
        await kernel.store.upsert_named_agent(
            NamedAgent(
                tenant_id=tenant_id,
                address="general",
                name="general",
                runtime="script",
                default_for_intake=True,
            )
        )
    log.info("agent support registered (skills, work reads, durable peer messaging)")
