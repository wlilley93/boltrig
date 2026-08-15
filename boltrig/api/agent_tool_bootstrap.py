"""Register the always-available, policy-scoped agent support tools."""

from __future__ import annotations

import logging

from boltrig.kernel import Kernel
from boltrig.kernel.work_read_adapter import build_work_read_adapter
from boltrig.skills.shelf import build_skill_shelf_adapter

log = logging.getLogger("boltrig.bootstrap")


async def register_agent_support(kernel: Kernel, tenant_id: str) -> None:
    """Register progressive skill discovery and read-only canonical Work access."""

    await kernel.register_adapter(tenant_id, build_skill_shelf_adapter(kernel.store))
    await kernel.register_adapter(tenant_id, build_work_read_adapter(kernel.store))
    log.info("agent support registered (skill.search/describe/load, work.list/get)")
