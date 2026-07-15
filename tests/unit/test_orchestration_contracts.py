from __future__ import annotations

import pickle
from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError

import pytest

from boltrig.fleet.application import PhaseLifecycle, RuntimeBindingError
from boltrig.fleet.domain import (
    CanonicalJSON,
    EffectiveAuthority,
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseRef,
    ProfileRef,
    RecordedRuntimeEvent,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SkillVersionRef,
)
from boltrig.fleet.ports import (
    EphemeralBearer,
    RuntimeThreadSpec,
    RuntimeTurnSpec,
    TurnSteerRequest,
)
from boltrig.models import GrantSet


class _FakeRuntime:
    name = "fake"

    def __init__(self, returned_assignment: PhaseAssignmentRef | None = None) -> None:
        self.started_turn: RuntimeTurnSpec | None = None
        self.returned_assignment = returned_assignment

    async def start_thread(self, spec: RuntimeThreadSpec) -> RuntimeThreadRef:
        return RuntimeThreadRef(
            assignment=self.returned_assignment or spec.assignment,
            runtime=self.name,
            thread_id="bound-thread",
        )

    async def resume_thread(self, thread: RuntimeThreadRef) -> RuntimeThreadRef:
        return thread

    async def start_turn(self, spec: RuntimeTurnSpec) -> RuntimeTurnRef:
        self.started_turn = spec
        return RuntimeTurnRef(thread=spec.thread, turn_id="turn-1")

    async def steer_turn(self, request: TurnSteerRequest) -> RuntimeTurnRef:
        return request.turn

    async def interrupt_turn(self, turn: RuntimeTurnRef) -> None:
        del turn

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        del thread

        async def empty() -> AsyncIterator[RuntimeEvent]:
            if False:
                yield  # pragma: no cover

        return empty()

    async def close_thread(self, thread: RuntimeThreadRef) -> None:
        del thread


def _authority(**replacements: GrantSet) -> EffectiveAuthority:
    values = {
        "parent_grant": GrantSet.of(["ticket.*"]),
        "profile_ceiling": GrantSet.of(["*"]),
        "selected_skill_requirements": GrantSet.of(["ticket.read"]),
        "workspace_policy": GrantSet.of(["ticket.*"]),
        "approval_state": GrantSet.of(["*"]),
    }
    values.update(replacements)
    return EffectiveAuthority(**values)


def _assignment(suffix: str = "1") -> PhaseAssignmentRef:
    phase = PhaseRef(
        root_run_id=f"run-{suffix}",
        phase_id=f"phase-{suffix}",
        principal=OrganisationUserRef(tenant_id="org-1", user_id="user-1"),
        workspace_id="workspace-1",
    )
    return PhaseAssignmentRef(phase=phase, assignment_id=f"assignment-{suffix}")


@pytest.mark.invariant("SEC-144")
def test_effective_authority_requires_every_current_ceiling() -> None:
    authority = _authority()

    assert authority.permits("ticket.read")
    assert not authority.permits("ticket.write")
    assert authority.denied_by("ticket.write") == ("selected_skill_requirements",)

    labels = (
        "parent_grant",
        "profile_ceiling",
        "selected_skill_requirements",
        "workspace_policy",
        "approval_state",
    )
    for label in labels:
        narrowed = _authority(**{label: GrantSet.of(["other.read"])})
        assert not narrowed.permits("ticket.read")
        assert label in narrowed.denied_by("ticket.read")


@pytest.mark.invariant("SEC-144")
def test_skill_selection_cannot_widen_authority_and_refs_are_immutable() -> None:
    authority = _authority(selected_skill_requirements=GrantSet.of(["*"]))
    phase = PhaseRef(
        root_run_id="run-1",
        phase_id="phase-1",
        principal=OrganisationUserRef(tenant_id="org-1", user_id="user-1"),
        workspace_id="workspace-1",
    )
    profile = ProfileRef(name="head_of_legal", version="1")
    selected_skill = SkillVersionRef(name="contracts", version="4")
    assignment = PhaseAssignmentRef(phase=phase, assignment_id="assignment-1")
    thread = RuntimeThreadRef(
        assignment=assignment,
        runtime="codex-app-server",
        thread_id="thread-1",
    )
    turn = RuntimeTurnRef(thread=thread, turn_id="turn-1")

    assert not authority.permits("admin.users.deactivate")
    assert selected_skill.name == "contracts"
    with pytest.raises(FrozenInstanceError):
        authority.parent_grant = GrantSet.of(["*"])  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        profile.name = "root"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        phase.workspace_id = "workspace-2"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        turn.turn_id = "prompt-selected-turn"  # type: ignore[misc]


async def test_phase_lifecycle_binds_a_new_turn_to_the_runtime_thread() -> None:
    runtime = _FakeRuntime()
    lifecycle = PhaseLifecycle(runtime)
    assignment = _assignment()
    thread_spec = RuntimeThreadSpec(
        assignment=assignment,
        profile=ProfileRef(name="researcher", version="1"),
        skills=(),
        working_directory="/workspace",
    )

    turn = await lifecycle.start(
        thread_spec,
        prompt="Find the evidence",
        client_message_id="message-1",
    )

    assert turn.thread.thread_id == "bound-thread"
    assert runtime.started_turn is not None
    assert runtime.started_turn.thread == turn.thread
    assert runtime.started_turn.prompt == "Find the evidence"


@pytest.mark.invariant("SEC-145")
async def test_phase_lifecycle_rejects_a_cross_assignment_thread() -> None:
    expected = _assignment("expected")
    runtime = _FakeRuntime(returned_assignment=_assignment("wrong"))
    lifecycle = PhaseLifecycle(runtime)
    spec = RuntimeThreadSpec(
        assignment=expected,
        profile=ProfileRef(name="researcher", version="1"),
        skills=(),
        working_directory="/workspace",
    )

    with pytest.raises(RuntimeBindingError, match="another phase assignment"):
        await lifecycle.start(spec, prompt="Bound work", client_message_id="message-1")


@pytest.mark.invariant("SEC-145")
def test_runtime_event_rejects_cross_assignment_thread_or_turn() -> None:
    expected = _assignment("expected")
    wrong = _assignment("wrong")
    wrong_thread = RuntimeThreadRef(assignment=wrong, runtime="codex", thread_id="thread-1")

    with pytest.raises(ValueError, match="another assignment"):
        RuntimeEvent(
            event_id="event-1",
            assignment=expected,
            kind=RuntimeEventKind.THREAD_STARTED,
            thread=wrong_thread,
        )

    event = RuntimeEvent(
        event_id="event-2",
        assignment=expected,
        kind=RuntimeEventKind.WARNING,
    )
    assert RecordedRuntimeEvent(event=event, sequence=1).sequence == 1
    with pytest.raises(ValueError, match="positive"):
        RecordedRuntimeEvent(event=event, sequence=0)
    with pytest.raises(ValueError, match="thread_id"):
        RuntimeThreadRef(assignment=expected, runtime="codex", thread_id="")


@pytest.mark.invariant("SEC-146")
def test_canonical_json_is_copied_finite_and_immutable() -> None:
    source = {"nested": {"items": [1, 2]}}
    document = CanonicalJSON.from_mapping(source)
    source["nested"]["items"].append(3)  # type: ignore[index,union-attr]
    first_copy = document.to_mapping()
    first_copy["replacement"] = True

    assert document.to_mapping() == {"nested": {"items": [1, 2]}}
    with pytest.raises(ValueError, match="canonical JSON"):
        CanonicalJSON.from_mapping({"bad": float("nan")})


@pytest.mark.invariant("SEC-146")
def test_ephemeral_bearer_is_explicitly_revealed_but_not_serializable() -> None:
    bearer = EphemeralBearer("top-secret-token")

    assert bearer.reveal() == "top-secret-token"
    assert "top-secret-token" not in repr(bearer)
    assert not hasattr(bearer, "__dict__")
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(bearer)
