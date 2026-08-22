"""Assignment and event helpers for the one-shot Codex runtime adapter."""

from __future__ import annotations

import logging
import os

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


#: Item types that are the model USING a tool - the unit a runaway weak-model
#: loop spends (dev measured ~231s per model call around each one). Reasoning,
#: messages and plans are thinking, not steps, and never count.
TOOL_ITEM_TYPES = frozenset(
    {
        "collabAgentToolCall",
        "commandExecution",
        "dynamicToolCall",
        "fileChange",
        "imageGeneration",
        "mcpToolCall",
        "webSearch",
    }
)


#: The default per-turn tool-step budget. Sized for a chat turn's real work
#: (a handful of verbs) with headroom, while a weak model looping on its
#: harness stops in bounded time. ``BOLTRIG_CODEX_MAX_TOOL_STEPS`` overrides
#: per deployment; an explicit ``0`` disables the cap (the operator's call,
#: never a fallback); an unparsable value keeps the default rather than
#: silently uncapping.
DEFAULT_MAX_TOOL_STEPS = 16
_MAX_TOOL_STEPS_ENV = "BOLTRIG_CODEX_MAX_TOOL_STEPS"


def tool_step_cap_from_env() -> int | None:
    raw = os.environ.get(_MAX_TOOL_STEPS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_TOOL_STEPS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_TOOL_STEPS
    if value == 0:
        return None
    return value if value > 0 else DEFAULT_MAX_TOOL_STEPS


class ToolBudgetExhausted(Exception):
    """A turn started more tool steps than its budget allows.

    Raised by ``drain_until_complete`` when the (max+1)th tool item STARTS, so
    at most ``max`` tool steps ever complete; carries what the turn had already
    consumed because the provider was paid for it either way."""

    def __init__(self, steps: int, tokens: int) -> None:
        super().__init__(f"tool budget exhausted after {steps} tool steps")
        self.steps = steps
        self.tokens = tokens


async def drain_until_complete(
    events: AsyncIterator[RuntimeEvent],
    seen: list[int] | None = None,
    legs: dict[str, int] | None = None,
    errors: list[Mapping[str, object]] | None = None,
    *,
    max_tool_steps: int | None = None,
) -> int:
    """Drain lifecycle events and retain the latest content-free usage report.

    ``max_tool_steps`` bounds the turn's TOOL work: a weak model that loops on
    its tool harness otherwise burns unbounded wall-clock (9+ minutes measured
    before the first cap existed). None means unbounded - the operator's
    explicit choice, never a fallback."""

    tokens = 0
    tool_steps = 0
    async for event in events:
        if event.kind is RuntimeEventKind.ITEM_STARTED and max_tool_steps is not None:
            payload = event.payload.to_mapping()
            if payload.get("item_type") in TOOL_ITEM_TYPES:
                tool_steps += 1
                if tool_steps > max_tool_steps:
                    raise ToolBudgetExhausted(tool_steps, tokens)
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


def budget_exhausted_result(runtime, prompt, exhausted, legs, *, run_id):
    """The degrade an exhausted tool budget answers with: the reason names the
    budget that was honoured (steps-1: the trip is the refusal of the step
    AFTER it), and the usage is what the provider was already paid for."""

    from .result import AgentResult

    logger.warning(
        "codex turn hit its tool-step budget (%d) for run %s",
        exhausted.steps - 1,
        run_id,
    )
    return AgentResult.degrade(
        runtime=runtime,
        reason=f"codex_tool_budget_exhausted:{exhausted.steps - 1}",
        prompt=prompt,
        tokens_used=exhausted.tokens,
        input_tokens=legs.get("input_tokens", 0),
        output_tokens=legs.get("output_tokens", 0),
    )


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
