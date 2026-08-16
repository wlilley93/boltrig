"""Relay-driven turn streaming with bounded browser projection."""

from __future__ import annotations

import asyncio
import contextlib

from .chat_event_projection import project_chat_event
from .turn_executor_compat import invoke_turn_executor


async def safe_exec(service, kwargs: dict) -> None:
    run_id = kwargs["run_id"]
    try:
        await invoke_turn_executor(
            service._exec,  # noqa: SLF001
            relay=service._relay.for_tenant(kwargs["tenant_id"]),  # noqa: SLF001
            kwargs=kwargs,
        )
    except Exception as exc:
        service._relay.publish(  # noqa: SLF001
            kwargs["tenant_id"],
            run_id,
            {
                "type": "text_delta",
                "delta": f"(turn error: {type(exc).__name__})",
            },
        )
    finally:
        service._relay.close(kwargs["tenant_id"], run_id)  # noqa: SLF001


async def drive_turn_events(
    service,
    *,
    tenant_id,
    user_id,
    conversation_id,
    run_id,
    message,
    role,
    grants,
    attachments,
    heartbeat,
    workspace_id,
    scope,
    on_behalf_bearer,
    origin,
    model_profile_id,
    model_choice_id,
):
    if service._exec is None:  # noqa: SLF001
        yield {"type": "text_delta", "delta": "(no runtime configured)"}
        return
    task = asyncio.create_task(
        service._safe_exec(  # noqa: SLF001
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            message=message,
            role=role,
            grants=grants,
            attachments=attachments or [],
            workspace_id=workspace_id,
            scope=scope,
            on_behalf_bearer=on_behalf_bearer,
            origin=origin,
            model_profile_id=model_profile_id,
            model_choice_id=model_choice_id,
        )
    )
    interval = service._cfg.heartbeat_seconds if heartbeat else 0  # noqa: SLF001
    if service._relay.shared:  # noqa: SLF001
        # Shared active-run ownership is leased. Production therefore keeps a
        # bounded renewal beat even when transport heartbeats were configured
        # off or above the lease's safe renewal window.
        interval = min(30.0, interval) if interval > 0 else 15.0
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def pump_events() -> None:
        try:
            async for event in service._relay.subscribe(  # noqa: SLF001
                tenant_id, run_id, replay=True
            ):
                await queue.put(event)
        finally:
            await queue.put(done)

    pump = asyncio.create_task(pump_events())
    try:
        while True:
            try:
                item = (
                    await asyncio.wait_for(queue.get(), timeout=interval)
                    if interval and interval > 0
                    else await queue.get()
                )
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "run_id": run_id}
                continue
            if item is done:
                break
            yield project_chat_event(item)
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await task
