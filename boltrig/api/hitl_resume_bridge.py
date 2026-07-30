"""HITL answer-side held-write replay bridge."""

from __future__ import annotations

import logging

from boltrig.kernel.workflow_trigger_finalization import (
    approval_requires_origin_finalization,
)
from boltrig.models import HITLType

log = logging.getLogger("boltrig.bootstrap")


async def resume_held_write_route(kernel, resume, request) -> None:
    """Replay an exact held write unless its show-once secret needs the caller."""
    if resume is None or request.type != HITLType.APPROVAL or not request.run_id:
        return
    try:
        if await approval_requires_origin_finalization(kernel.store, request):
            return
        from boltrig.kernel.held_call import held_write_is_waiting

        if not await held_write_is_waiting(
            kernel.store, request.tenant_id, request.run_id, request.id
        ):
            return
        await resume(request.tenant_id, request.run_id, request.id)
    except Exception:
        log.warning("held-write resume failed", exc_info=True)
