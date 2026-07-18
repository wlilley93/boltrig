"""Lifecycle port implemented by Codex App Server and test runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from boltrig.fleet.domain import (
    CanonicalJSON,
    PhaseMode,
    PhaseAssignmentRef,
    ProfileRef,
    RuntimeEvent,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SandboxPolicy,
    SkillVersionRef,
)


@dataclass(frozen=True)
class RuntimeThreadSpec:
    """Boltrig-owned birth configuration for a runtime thread."""

    assignment: PhaseAssignmentRef
    profile: ProfileRef
    skills: tuple[SkillVersionRef, ...]
    working_directory: str
    mode: PhaseMode = PhaseMode.READ_ONLY
    sandbox: SandboxPolicy = SandboxPolicy.READ_ONLY
    metadata: CanonicalJSON = field(default_factory=CanonicalJSON.empty_mapping)


@dataclass(frozen=True)
class RuntimeTurnSpec:
    """User input for a new turn; policy remains outside the prompt."""

    thread: RuntimeThreadRef
    prompt: str
    client_message_id: str
    output_schema: CanonicalJSON | None = None


@dataclass(frozen=True)
class TurnSteerRequest:
    """Additional input tied to the expected active turn."""

    turn: RuntimeTurnRef
    prompt: str
    client_message_id: str


class AgentRuntime(Protocol):
    """Vendor-neutral bounded-phase lifecycle owned by an execution runtime."""

    name: str

    async def start_thread(self, spec: RuntimeThreadSpec) -> RuntimeThreadRef: ...

    async def resume_thread(self, thread: RuntimeThreadRef) -> RuntimeThreadRef: ...

    async def start_turn(self, spec: RuntimeTurnSpec) -> RuntimeTurnRef: ...

    async def steer_turn(self, request: TurnSteerRequest) -> RuntimeTurnRef: ...

    async def interrupt_turn(self, turn: RuntimeTurnRef) -> None: ...

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]: ...

    async def close_thread(self, thread: RuntimeThreadRef) -> None: ...
