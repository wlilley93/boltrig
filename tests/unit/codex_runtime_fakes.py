from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

from boltrig.fleet.application.birth_policies import compile_birth_policy
from boltrig.fleet.domain import (
    CanonicalJSON,
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseRef,
    ProfileRef,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SandboxPolicy,
    SkillVersionRef,
)
from boltrig.fleet.domain.profile_policy import BirthPolicyRequest, StaticRoleProfile
from boltrig.fleet.domain.profile_policy import VersionedSkillManifest
from boltrig.fleet.domain.profile_policy_values import (
    DigestPinnedContent,
    ExactModelPolicy,
    NativeSubagentLimits,
    NativeSubagentPolicy,
    ReasoningEffort,
    RuntimeToolPolicy,
)
from boltrig.fleet.domain.skill_attestation import (
    ExpectedSkill,
    SkillAttestationPlan,
    SkillDiscoveryReport,
    SkillScope,
    attest_skill_discovery,
)
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient
from boltrig.fleet.infrastructure.codex_cell_policy import (
    CODEX_CLI_SHA256,
    CODEX_CLI_TARGET,
    CODEX_CLI_VERSION,
    CodexCellLayout,
)
from boltrig.fleet.infrastructure.codex_cell_supervisor import (
    CodexCellMetadata,
    InitializedCodexCell,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    AdmittedCodexCell,
    CodexPhaseAdmission,
    CodexWorkspaceProjectionBinding,
    QuarantinedCodexPreflightReceipt,
)
from boltrig.fleet.infrastructure.codex_stdio_transport import CodexStdioTransport
from boltrig.fleet.ports.runtime import RuntimeThreadSpec
from boltrig.fleet.infrastructure.skill_artifacts import SanitizedWorkspaceProjection

INSTRUCTIONS = "Stay bounded and report only verified evidence."
_ValueT = TypeVar("_ValueT")


def digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def assignment(suffix: str = "1") -> PhaseAssignmentRef:
    return PhaseAssignmentRef(
        PhaseRef(
            root_run_id=f"run-{suffix}",
            phase_id=f"phase-{suffix}",
            principal=OrganisationUserRef("org-1", "user-1"),
            workspace_id="workspace-1",
        ),
        f"assignment-{suffix}",
    )


def admission(
    exact_assignment: PhaseAssignmentRef | None = None,
    *,
    native_limits: NativeSubagentLimits = NativeSubagentLimits(),
    runtime_tools: tuple[str, ...] = (),
    skill_manifests: tuple[VersionedSkillManifest, ...] = (),
) -> CodexPhaseAdmission:
    binding = exact_assignment or assignment()
    profile = StaticRoleProfile(
        "researcher",
        "1.0.0",
        DigestPinnedContent(
            "profiles/researcher/1.0.0/instructions.md", digest(INSTRUCTIONS)
        ),
        ExactModelPolicy("gpt-5.4-codex", ReasoningEffort.HIGH),
        RuntimeToolPolicy(runtime_tools, runtime_tools),
        SandboxPolicy.READ_ONLY,
        SandboxPolicy.READ_ONLY,
        tuple(item.pin for item in skill_manifests),
        NativeSubagentPolicy(native_limits, native_limits),
    )
    compilation = compile_birth_policy(
        BirthPolicyRequest(
            profile.pin,
            selected_skills=tuple(item.pin for item in skill_manifests),
            requested_native_subagents=native_limits,
        ),
        profile,
        skill_manifests,
    )
    workspace = "/srv/boltrig/cells/cell-1/workspace"
    projection = SanitizedWorkspaceProjection(
        "/srv/boltrig/sources/workspace-1",
        workspace,
        digest("workspace"),
        1,
        12,
    )
    layout = CodexCellLayout(
        binding.phase.phase_id,
        "cell-1",
        Path("/srv/boltrig"),
        Path("/srv/boltrig/cells/cell-1"),
        projection,
        Path("/srv/boltrig/cells/cell-1/home"),
        Path("/srv/boltrig/cells/cell-1/codex-home"),
    )
    selected = tuple(
        ExpectedSkill(
            item.name,
            f"/srv/boltrig/cells/cell-1/codex-home/skills/{item.name}/SKILL.md",
            SkillScope.USER,
            item.artifact_directory_digest,
            item.artifact.digest,
        )
        for item in skill_manifests
    )
    return CodexPhaseAdmission(
        binding,
        layout,
        CodexWorkspaceProjectionBinding(binding, projection),
        compilation,
        skill_manifests,
        SkillAttestationPlan(workspace, selected, generation=1),
        INSTRUCTIONS,
        compilation.policy.digest(),
    )


def thread_spec(value: CodexPhaseAdmission) -> RuntimeThreadSpec:
    policy = value.compilation.policy
    return RuntimeThreadSpec(
        assignment=value.assignment,
        profile=ProfileRef(policy.profile.name, policy.profile.version),
        skills=tuple(
            SkillVersionRef(item.name, item.version)
            for item in value.selected_skill_manifests
        ),
        working_directory=value.layout.workspace.as_posix(),
    )


class FakeCodexClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.notifications: asyncio.Queue[wire.NotificationMessage | Exception] = asyncio.Queue()
        self.thread_start_gate: asyncio.Event | None = None
        self.turn_start_gate: asyncio.Event | None = None
        self.thread_id = "thread-1"
        self.turn_id = "turn-1"
        self.close_calls = 0
        self.active_notification_readers = 0
        self.max_notification_readers = 0
        self._state = wire.ClientState.READY

    @property
    def state(self) -> wire.ClientState:
        return self._state

    async def thread_start(self, **kwargs: Any) -> wire.ThreadResult:
        self.calls.append(("thread_start", kwargs))
        if self.thread_start_gate is not None:
            await self.thread_start_gate.wait()
        self.notifications.put_nowait(
            wire.NotificationMessage(
                "thread/started",
                CanonicalJSON.from_mapping(
                    {
                        "thread": {
                            "cliVersion": CODEX_CLI_VERSION,
                            "cwd": kwargs["cwd"],
                            "ephemeral": True,
                            "id": self.thread_id,
                            "parentThreadId": None,
                        }
                    }
                ),
            )
        )
        return wire.ThreadResult(1, "thread/start", self.thread_id, CanonicalJSON.empty_mapping())

    async def thread_resume(self, thread_id: str, **kwargs: Any) -> wire.ThreadResult:
        self.calls.append(("thread_resume", {"thread_id": thread_id, **kwargs}))
        return wire.ThreadResult(2, "thread/resume", thread_id, CanonicalJSON.empty_mapping())

    async def turn_start(self, thread_id: str, **kwargs: Any) -> wire.TurnResult:
        self.calls.append(("turn_start", {"thread_id": thread_id, **kwargs}))
        if self.turn_start_gate is not None:
            await self.turn_start_gate.wait()
        self.notifications.put_nowait(
            wire.NotificationMessage(
                "turn/started",
                CanonicalJSON.from_mapping(
                    {
                        "threadId": thread_id,
                        "turn": {"id": self.turn_id, "items": [], "status": "inProgress"},
                    }
                ),
            )
        )
        return wire.TurnResult(3, "turn/start", self.turn_id, CanonicalJSON.empty_mapping())

    async def turn_steer(self, thread_id: str, **kwargs: Any) -> wire.TurnResult:
        self.calls.append(("turn_steer", {"thread_id": thread_id, **kwargs}))
        return wire.TurnResult(4, "turn/steer", self.turn_id, CanonicalJSON.empty_mapping())

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> wire.CallReceipt:
        self.calls.append(("turn_interrupt", {"thread_id": thread_id, "turn_id": turn_id}))
        return wire.CallReceipt(5, "turn/interrupt", CanonicalJSON.empty_mapping())

    async def next_notification(self, *, timeout: float | None = None) -> wire.NotificationMessage:
        self.active_notification_readers += 1
        self.max_notification_readers = max(
            self.max_notification_readers, self.active_notification_readers
        )
        try:
            if not self.notifications.empty():
                value = self.notifications.get_nowait()
            elif timeout == 0:
                raise TimeoutError
            elif timeout is None:
                value = await self.notifications.get()
            else:
                value = await asyncio.wait_for(self.notifications.get(), timeout)
            if isinstance(value, Exception):
                raise value
            return value
        finally:
            self.active_notification_readers -= 1

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self.notifications.put(
            wire.NotificationMessage(method, CanonicalJSON.from_mapping(params))
        )

    async def aclose(self) -> None:
        self.close_calls += 1
        self._state = wire.ClientState.CLOSED
        if self.thread_start_gate is not None:
            self.thread_start_gate.set()
        if self.turn_start_gate is not None:
            self.turn_start_gate.set()
        self.notifications.put_nowait(RuntimeError("closed"))


@dataclass
class _FakeTransport:
    returncode: int | None = None

    async def aclose(self) -> None:
        self.returncode = 0


@dataclass(repr=False)
class FakeCodexCell:
    initialized: InitializedCodexCell
    client: FakeCodexClient
    transport: _FakeTransport
    releases: list[tuple[str, str]]

    @property
    def closed(self) -> bool:
        return self.initialized.closed

    @property
    def close_calls(self) -> int:
        return self.client.close_calls

    @property
    def returncode(self) -> int | None:
        return self.transport.returncode

    @returncode.setter
    def returncode(self, value: int | None) -> None:
        self.transport.returncode = value


class FakeCellProvider:
    def __init__(self, *cells: AdmittedCodexCell) -> None:
        self.cells = list(cells)
        self.calls: list[PhaseAssignmentRef] = []

    async def acquire(self, exact_assignment: PhaseAssignmentRef) -> AdmittedCodexCell:
        self.calls.append(exact_assignment)
        return self.cells.pop(0)


def leased_cell(value: CodexPhaseAdmission) -> tuple[AdmittedCodexCell, FakeCodexCell]:
    fake = fake_cell(value)
    return AdmittedCodexCell(value, fake.initialized, preflight_receipt(value)), fake


def preflight_receipt(value: CodexPhaseAdmission) -> QuarantinedCodexPreflightReceipt:
    report = SkillDiscoveryReport(value.skill_plan.workspace_path, ())
    return QuarantinedCodexPreflightReceipt(
        attest_skill_discovery(value.skill_plan, report),
    )


def fake_cell(
    value: CodexPhaseAdmission,
    *,
    metadata_admission: CodexPhaseAdmission | None = None,
) -> FakeCodexCell:
    metadata_source = metadata_admission or value
    layout = metadata_source.layout
    client = FakeCodexClient()
    transport = _FakeTransport()
    releases: list[tuple[str, str]] = []

    async def release(phase_id: str, cell_id: str) -> None:
        releases.append((phase_id, cell_id))

    metadata = CodexCellMetadata(
        phase_id=layout.phase_id,
        cell_id=layout.cell_id,
        pid=1234,
        cli_version=CODEX_CLI_VERSION,
        cli_target=CODEX_CLI_TARGET,
        binary_sha256=CODEX_CLI_SHA256,
        binary_path=Path("/opt/boltrig/codex"),
        workspace=layout.workspace,
        workspace_digest=layout.workspace_digest,
        home=layout.home,
        codex_home=layout.codex_home,
        platform_family="unix",
        platform_os="linux",
        user_agent="boltrig/0.1 codex/0.144.3",
    )
    initialized = InitializedCodexCell(
        cast(CodexAppServerClient, client),
        metadata,
        cast(CodexStdioTransport, transport),
        release,
    )
    return FakeCodexCell(initialized, client, transport, releases)


async def collect(iterator: AsyncIterator[_ValueT], count: int) -> list[_ValueT]:
    return [await anext(iterator) for _ in range(count)]


def wrong_thread(thread: RuntimeThreadRef) -> RuntimeThreadRef:
    return RuntimeThreadRef(assignment("wrong"), thread.runtime, thread.thread_id)


def wrong_turn(turn: RuntimeTurnRef) -> RuntimeTurnRef:
    return RuntimeTurnRef(wrong_thread(turn.thread), turn.turn_id)
