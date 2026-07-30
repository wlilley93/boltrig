"""Construct a Codex event translator from one admitted runtime policy."""

from __future__ import annotations

from boltrig.fleet.domain import CompiledBirthPolicy, PhaseAssignmentRef, RuntimeThreadRef

from .codex_runtime_events import CodexEventTranslator


def build_codex_event_translator(
    *,
    assignment: PhaseAssignmentRef,
    thread: RuntimeThreadRef,
    cwd: str,
    policy: CompiledBirthPolicy,
) -> CodexEventTranslator:
    return CodexEventTranslator(
        assignment=assignment,
        thread=thread,
        cwd=cwd,
        max_native_concurrent=policy.native_subagents.max_concurrent,
        max_native_total=policy.native_subagents.max_total,
        max_native_depth=policy.native_subagents.max_depth,
        model_id=policy.model.model_id,
        reasoning_effort=policy.model.reasoning_effort.value,
    )
