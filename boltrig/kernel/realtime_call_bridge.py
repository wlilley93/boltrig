"""Project held-call outcomes onto their owning realtime call.

Authority remains entirely in the ordinary held-write replay.  This module
adds only a content-free observation after that replay: the call id came from
the server-minted MCP token and the canonical verb/params remain in the sealed
held-call record.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from boltrig.models import RealtimeCallEvent, utcnow

log = logging.getLogger("boltrig.kernel.realtime_call_bridge")

async def project_realtime_hitl_outcome(
    store,
    held,
    status: str,
    *,
    new_request_id: str | None = None,
) -> None:
    """Best-effort observation; it can never change the resumed action."""
    try:
        await _project(store, held, status, new_request_id=new_request_id)
    except Exception:  # noqa: BLE001 - dispatcher outcome already stands
        log.warning("realtime held-call projection failed", exc_info=True)


async def _project(
    store,
    held,
    status: str,
    *,
    new_request_id: str | None,
) -> None:
    call_id = str(held.context.extra.get("realtime_call") or "")
    if not call_id:
        return
    call = await store.get_realtime_call(held.context.tenant_id, call_id)
    if call is None or call.run_id != held.run_id or call.status == "ended":
        return
    await store.append_realtime_call_event(
        RealtimeCallEvent(
            id=f"callhitl_{held.request_id}_{status}",
            tenant_id=held.context.tenant_id,
            call_id=call_id,
            type="hitl",
            payload={
                "request_id": held.request_id,
                "status": status,
                "verb": held.verb,
            },
            participant_id="boltrig-agent",
        )
    )
    await store.append_realtime_call_event(
        RealtimeCallEvent(
            id=f"calltool_{held.request_id}_{status}",
            tenant_id=held.context.tenant_id,
            call_id=call_id,
            type="tool_result",
            payload={"verb": held.verb, "status": status},
            participant_id="boltrig-agent",
        )
    )
    next_status = "held" if status == "re_pended" else "active"
    await store.update_realtime_call(
        replace(call, status=next_status, updated_at=utcnow())
    )
    if new_request_id:
        await store.append_realtime_call_event(
            RealtimeCallEvent(
                id=f"callhitl_{new_request_id}_pending",
                tenant_id=held.context.tenant_id,
                call_id=call_id,
                type="hitl",
                payload={
                    "request_id": new_request_id,
                    "status": "pending",
                    "verb": held.verb,
                },
                participant_id="boltrig-agent",
            )
        )
