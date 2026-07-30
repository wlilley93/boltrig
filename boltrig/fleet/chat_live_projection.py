"""Browser-safe live continuity over the canonical chat run.

This module owns the reattachment mechanics so ``ChatService`` remains focused
on turn orchestration. It deliberately uses the relay's active-run truth and
the existing access predicate instead of inventing a second run authority.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from boltrig.fleet.chat_conversation_access import (
    ConversationForbidden,
    can_read_conversation,
)
from boltrig.fleet.chat_event_projection import project_chat_event


class ChatLiveProjection:
    """Resolve and follow one authorized conversation's server-owned live run."""

    def __init__(
        self,
        service: Any,
    ) -> None:
        self._service = service

    async def active_run_for(
        self, tenant_id: str, user_id: str, role: str, conversation_id: str
    ) -> str | None:
        """Return only the server-owned active run for an authorized thread."""
        conversation = await self._service._store.get_conversation(  # noqa: SLF001
            tenant_id, conversation_id
        )
        if conversation is None or not can_read_conversation(conversation, user_id, role):
            raise ConversationForbidden("no such conversation")
        async with self._service._lock_for(tenant_id, conversation_id):  # noqa: SLF001
            return self._service._active_run_for(  # noqa: SLF001
                tenant_id, conversation_id
            )

    def replay_state(self, tenant_id: str, run_id: str, since: int | None) -> tuple[int, bool]:
        """Clamp a client cursor to relay truth and report bounded-buffer loss."""
        oldest, latest = self._service._relay.seq_bounds(  # noqa: SLF001
            tenant_id, run_id
        )
        effective = min(max(0, since or 0), latest)
        return effective, oldest is not None and oldest > effective + 1

    async def follow(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        since: int = 0,
    ) -> AsyncIterator[tuple[int, dict[str, Any]]]:
        """Replay then follow through the browser-safe projection.

        Quiet runs emit cursor-preserving heartbeats. The local pump keeps a
        timed-out heartbeat from cancelling the relay iterator, which would
        otherwise silently detach the subscription.
        """
        queue: asyncio.Queue = asyncio.Queue()
        done = object()

        async def pump_relay() -> None:
            try:
                async for item in self._service._relay.subscribe_with_seq(  # noqa: SLF001
                    tenant_id, run_id, replay=True, since=since
                ):
                    await queue.put(item)
            finally:
                await queue.put(done)

        pump = asyncio.create_task(pump_relay())
        interval = max(1, int(self._service._cfg.heartbeat_seconds))  # noqa: SLF001
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=interval)
                except asyncio.TimeoutError:
                    yield (
                        self._service._relay.max_seq(tenant_id, run_id),
                        {  # noqa: SLF001
                            "type": "heartbeat",
                            "run_id": run_id,
                        },
                    )
                    continue
                if item is done:
                    break
                seq, event = item
                yield seq, project_chat_event(event)
        finally:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
        # Relay close precedes assistant-message persistence and the active-map
        # hand-off. Do not tell a reconnecting browser "ended" until that canonical
        # boundary is visible, or it can refresh during the narrow empty gap.
        while True:
            async with self._service._lock_for(  # noqa: SLF001
                tenant_id, conversation_id
            ):
                if (
                    self._service._active_run_for(  # noqa: SLF001
                        tenant_id, conversation_id
                    )
                    != run_id
                ):
                    return
            await asyncio.sleep(0.01)
