"""Transport-neutral turn coordination for durable named identities.

Every wake source eventually asks one named identity to take a turn.  This
coordinator is the reusable boundary between those sources and a model runtime:
it joins the durable priority queue, acquires the one fenced lease for the
identity, keeps that lease alive, and releases it on every exit path.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from boltrig.models import AgentTurnLane, AgentTurnLease

log = logging.getLogger("boltrig.fleet.agent_turns")

DEFAULT_AGENT_TURN_LEASE_SECONDS = 300
DEFAULT_AGENT_TURN_WAITER_TTL_SECONDS = 900
DEFAULT_AGENT_TURN_POLL_SECONDS = 0.1


class AgentTurnLeaseLost(RuntimeError):
    """The caller no longer owns the named identity's serialized turn."""


class AgentTurnCoordinator:
    """Acquire and heartbeat one named-agent turn across worker processes."""

    def __init__(
        self,
        store: Any,
        *,
        lease_seconds: int = DEFAULT_AGENT_TURN_LEASE_SECONDS,
        waiter_ttl_seconds: int = DEFAULT_AGENT_TURN_WAITER_TTL_SECONDS,
        poll_seconds: float = DEFAULT_AGENT_TURN_POLL_SECONDS,
    ) -> None:
        self._store = store
        self.lease_seconds = max(1, int(lease_seconds))
        self.waiter_ttl_seconds = max(
            self.lease_seconds, int(waiter_ttl_seconds)
        )
        self.poll_seconds = max(0.01, float(poll_seconds))

    @asynccontextmanager
    async def hold(
        self,
        tenant_id: str,
        agent_address: str,
        owner: str,
        lane: AgentTurnLane,
    ) -> AsyncIterator[AgentTurnLease]:
        """Wait for, heartbeat, and finally release one serialized turn."""
        lease: AgentTurnLease | None = None
        try:
            while lease is None:
                lease = await self._store.acquire_agent_turn(
                    tenant_id,
                    agent_address,
                    owner,
                    lane,
                    self.lease_seconds,
                    waiter_ttl_seconds=self.waiter_ttl_seconds,
                )
                if lease is None:
                    await asyncio.sleep(self.poll_seconds)
        except BaseException:
            try:
                await self._store.cancel_agent_turn_waiter(
                    tenant_id, agent_address, owner
                )
            except Exception:
                log.exception(
                    "failed to cancel named-agent waiter for %s", agent_address
                )
            raise

        lease_box = [lease]
        stop = asyncio.Event()
        lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(lease_box, stop, lost))
        try:
            yield lease
            await self._stop_heartbeat(heartbeat, stop)
            if lost.is_set():
                raise AgentTurnLeaseLost("named agent turn lease was lost")
        finally:
            await self._stop_heartbeat(heartbeat, stop)
            try:
                await self._store.release_agent_turn(lease_box[0])
            except Exception:
                # The finite lease remains the recovery boundary. A cleanup
                # transport failure must not replace the turn's real outcome.
                log.exception(
                    "failed to release named-agent turn for %s", agent_address
                )

    async def _heartbeat(
        self,
        lease_box: list[AgentTurnLease],
        stop: asyncio.Event,
        lost: asyncio.Event,
    ) -> None:
        interval = max(1.0, min(30.0, self.lease_seconds / 3))
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                try:
                    renewed = await self._store.renew_agent_turn(
                        lease_box[0], self.lease_seconds
                    )
                except Exception:
                    log.exception(
                        "named-agent turn heartbeat failed for %s",
                        lease_box[0].agent_address,
                    )
                    lost.set()
                    return
                if renewed is None:
                    lost.set()
                    return
                lease_box[0] = renewed

    @staticmethod
    async def _stop_heartbeat(task: asyncio.Task, stop: asyncio.Event) -> None:
        if task.done():
            await task
            return
        stop.set()
        await task


__all__ = [
    "AgentTurnCoordinator",
    "AgentTurnLeaseLost",
    "DEFAULT_AGENT_TURN_LEASE_SECONDS",
    "DEFAULT_AGENT_TURN_POLL_SECONDS",
    "DEFAULT_AGENT_TURN_WAITER_TTL_SECONDS",
]
