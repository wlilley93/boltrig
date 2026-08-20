"""Assignment and event helpers for the one-shot Codex runtime adapter."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping

from boltrig.fleet.domain import (
    PhaseAssignmentRef,
    PhaseRef,
    RuntimeEvent,
    RuntimeEventKind,
)
from boltrig.models import InvocationContext
from boltrig.models.execution_scope import OrganisationUserRef

logger = logging.getLogger(__name__)


def empty_output_reason(errors: list[Mapping[str, object]], run_id: str) -> str:
    if not errors:
        return "codex_empty_output"
    logger.warning(
        "codex reported %d runtime error(s) before an empty turn for run %s "
        "(will_retry=%s): %s",
        len(errors),
        run_id,
        [observed.get("will_retry") for observed in errors],
        # The runtime's ERROR payloads are already content-free lifecycle
        # reports; dropping them here left "1 runtime error(s)" as the whole
        # operator record of WHY a turn died (2026-08-20).
        [dict(observed) for observed in errors],
    )
    return "codex_empty_output_after_error"


async def drain_until_complete(
    events: AsyncIterator[RuntimeEvent],
    seen: list[int] | None = None,
    legs: dict[str, int] | None = None,
    errors: list[Mapping[str, object]] | None = None,
) -> int:
    """Drain lifecycle events and retain the latest content-free usage report."""

    tokens = 0
    async for event in events:
        if event.kind is RuntimeEventKind.ERROR:
            if errors is not None:
                errors.append(event.payload.to_mapping())
        elif event.kind is RuntimeEventKind.TOKEN_USAGE:
            payload = event.payload.to_mapping()
            reported = payload.get("total_tokens")
            if type(reported) is int and reported > 0:
                tokens = reported
                if seen is not None:
                    seen.append(reported)
                if legs is not None:
                    legs["input_tokens"] = _reported_leg(payload.get("input_tokens"))
                    legs["output_tokens"] = _reported_leg(payload.get("output_tokens"))
        elif event.kind is RuntimeEventKind.TURN_COMPLETED:
            return tokens
    return tokens


def _reported_leg(value: object) -> int:
    return value if type(value) is int and value > 0 else 0


def mint_assignment(
    context: InvocationContext, run_id: str, workspace_id: str
) -> PhaseAssignmentRef:
    principal = OrganisationUserRef(
        tenant_id=context.tenant_id,
        user_id=context.on_behalf_of or context.actor or "agent",
    )
    phase = PhaseRef(
        root_run_id=run_id,
        phase_id=f"{run_id}-codex",
        principal=principal,
        workspace_id=workspace_id,
    )
    return PhaseAssignmentRef(
        phase=phase,
        assignment_id=f"{run_id}-codex-assignment",
    )


__all__ = ["drain_until_complete", "empty_output_reason", "mint_assignment"]
