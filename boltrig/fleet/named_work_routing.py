"""Flat named-peer context seating and explicit work routing."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from boltrig.models import GrantSet, InvocationContext, WorkItem

log = logging.getLogger("boltrig.fleet.pump")


class NamedWorkRouting:
    """Mixin for a pump that may serve a flat named-agent roster."""

    def _named_context(
        self, context: InvocationContext, address: str
    ) -> InvocationContext:
        """Seat a peer without widening the principal's external authority."""
        return replace(
            context,
            grants=GrantSet.of(
                list(context.grants.allow) + ["agent.send"],
                list(context.grants.deny),
            ),
            actor=address,
            actor_tier="tier1",
            extra={**context.extra, "named_agent_address": address},
        )

    async def _route_to_named_agent(
        self, item: WorkItem, run_id: str
    ) -> Any | None:
        """Resolve an explicit peer address or the declared default, never infer."""
        await self._store.upsert_checkpoint(
            item.tenant_id, run_id, "route", "started"
        )
        target = str(getattr(item, "target", None) or "").strip()
        address = self._default_agent if target in {"", "cos"} else target
        agent = self.named_agents.get(address or "")
        if agent is None:
            log.warning("item %s addressed unknown named agent %r", item.id, address)
            return None
        item.owner_member = address
        await self._store.update_work_item(item)
        await self._store.upsert_checkpoint(
            item.tenant_id,
            run_id,
            "route",
            "done",
            output={"agent": address},
        )
        return agent
