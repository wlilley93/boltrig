from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from boltrig.fleet.domain import OrganisationUserRef as FleetOrganisationUserRef
from boltrig.fleet.domain import PhaseMode as FleetPhaseMode
from boltrig.fleet.domain import PhaseRef
from boltrig.models import execution_transitions as transitions
from boltrig.models import (
    AssignmentLease,
    AssignmentStatus,
    AttestationSetRef,
    AuthorityEvaluationRef,
    CancellationMetadata,
    EngineOwner,
    EvidenceKind,
    EvidenceRef,
    ExecutionAggregateKind,
    ExecutionAssignment,
    ExecutionPhase,
    ExecutionPhaseStatus,
    ExecutionResult,
    ExecutionRootRun,
    ExecutionScopeRef,
    ExecutionUsage,
    ExecutionVerification,
    ExecutionWorkItem,
    FindingSeverity,
    LedgerClaimOutcome,
    LedgerClaimStatus,
    LedgerMutationOutcome,
    LedgerMutationStatus,
    LedgerWorkItemStatus,
    OrganisationUserRef,
    PhaseMode,
    PhaseTerminalOutcome,
    ProfileVersionPin,
    ResultBlocker,
    ResultFinding,
    ResultHandoff,
    ResultStatus,
    RetryPolicy,
    RootRunStatus,
    RuntimeIdentity,
    SkillVersionPin,
    VerificationCheck,
    VerificationStatus,
    VerifierKind,
    VerifierRef,
    WorkspaceScopeRef,
    can_transition_assignment,
    can_transition_phase,
    can_transition_root_run,
    can_transition_verification,
    can_transition_work_item,
    runtime_phase_status_value,
)

NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


def _digest(value: str) -> str:
    return f"sha256:{value * 64}"


def _scope(tenant: str = "org-1", workspace: str = "workspace-1") -> ExecutionScopeRef:
    return ExecutionScopeRef(WorkspaceScopeRef(tenant, workspace), "run-1")


def _principal(tenant: str = "org-1", user: str = "user-1") -> OrganisationUserRef:
    return OrganisationUserRef(tenant, user)


def _profile(name: str = "head_of_legal") -> ProfileVersionPin:
    return ProfileVersionPin(name, "2.1.0", _digest("a"))


def _skills() -> tuple[SkillVersionPin, ...]:
    return (
        SkillVersionPin("contract-review", "4.0.1", _digest("b")),
        SkillVersionPin("case-research", "1.3.0", _digest("c")),
    )


def _authority() -> AuthorityEvaluationRef:
    return AuthorityEvaluationRef(
        "authority-1",
        _digest("9"),
        7,
        ("document.read", "ticket.read"),
        NOW,
    )


def _lease() -> AssignmentLease:
    return AssignmentLease("lease-1", "worker-1", NOW, NOW + timedelta(minutes=5))


def test_authority_evaluation_canonicalizes_exact_concrete_verbs() -> None:
    authority = AuthorityEvaluationRef(
        "authority-canonical",
        _digest("8"),
        7,
        ("ticket.read", "document.read", "ticket.read"),
        NOW,
    )

    assert authority.permitted_verbs == ("document.read", "ticket.read")


@pytest.mark.parametrize(
    "permitted_verbs",
    (
        ["ticket.read"],
        ("ticket.*",),
        ("ticket.\N{CYRILLIC SMALL LETTER A}",),
        ("x" * 257,),
        tuple(f"tool.verb{index}" for index in range(257)),
    ),
)
def test_authority_evaluation_rejects_noncanonical_or_unbounded_verbs(
    permitted_verbs: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="permitted|authority|bounded"):
        AuthorityEvaluationRef(
            "authority-invalid",
            _digest("7"),
            7,
            permitted_verbs,  # type: ignore[arg-type]
            NOW,
        )


def test_attestation_set_ref_requires_prefixed_digests_and_a_real_generation() -> None:
    """A raw, unprefixed digest is not a digest, so it cannot be referenced."""

    raw = "a" * 64
    with pytest.raises(ValueError, match="lowercase sha256 digest"):
        AttestationSetRef(2, raw, _digest("d"))
    with pytest.raises(ValueError, match="lowercase sha256 digest"):
        AttestationSetRef(2, _digest("c"), raw)
    with pytest.raises(ValueError, match="lowercase sha256 digest"):
        AttestationSetRef(2, _digest("c").upper(), _digest("d"))
    with pytest.raises(ValueError, match="catalog_generation"):
        AttestationSetRef(0, _digest("c"), _digest("d"))

    reference = AttestationSetRef(2, _digest("c"), _digest("d"))
    assert reference.attestation_set_digest == _digest("d")
    assert [field.name for field in fields(reference)] == [
        "catalog_generation",
        "catalog_digest",
        "attestation_set_digest",
    ]


@pytest.mark.invariant("FR-RUN-20")
def test_root_phase_work_assignment_are_scoped_pinned_and_boltrig_owned() -> None:
    scope = _scope()
    root = ExecutionRootRun(
        scope, _principal(), _digest("2"), _profile(), 7, RootRunStatus.RUNNING, created_at=NOW
    )
    phase = ExecutionPhase(
        scope,
        "phase-1",
        2,
        "research",
        _digest("3"),
        PhaseMode.READ_ONLY,
        _profile(),
        _skills(),
        7,
        ("phase-0",),
        RetryPolicy(3, 5, 30),
        ExecutionPhaseStatus.RUNNING,
        created_at=NOW,
    )
    work = ExecutionWorkItem(
        scope,
        "work-1",
        phase.id,
        1,
        _digest("d"),
        ("work-0",),
        status=LedgerWorkItemStatus.IN_FLIGHT,
        created_at=NOW,
    )
    assignment = ExecutionAssignment(
        scope,
        "assignment-2",
        phase.id,
        work.id,
        "runtime-user-1",
        2,
        _profile(),
        _skills(),
        _authority(),
        _lease(),
        replaces_assignment_id="assignment-1",
        status=AssignmentStatus.RUNNING,
        created_at=NOW,
    )

    assert all(item.scope == scope for item in (root, phase, work, assignment))
    assert all(item.engine_owner is EngineOwner.BOLTRIG for item in (root, phase, work, assignment))
    assert phase.objective_digest == _digest("3") and phase.policy_generation == 7
    assert assignment.authority.digest == _digest("9")
    assert assignment.authority.permitted_verbs == ("document.read", "ticket.read")
    assert assignment.replaces_assignment_id == "assignment-1"
    with pytest.raises(FrozenInstanceError):
        assignment.status = AssignmentStatus.COMPLETED  # type: ignore[misc]


def test_result_and_verification_are_structured_digest_only_records() -> None:
    evidence = EvidenceRef("evidence-1", EvidenceKind.TEST_RESULT, _digest("e"))
    finding = ResultFinding("contract.risk", FindingSeverity.HIGH, _digest("f"), (evidence.id,))
    blocker = ResultBlocker("approval.required", _digest("4"), (evidence.id,))
    handoff = ResultHandoff(_profile(), _digest("5"), (evidence.id,))
    result = ExecutionResult(
        _scope(),
        "result-1",
        "phase-1",
        "work-1",
        "assignment-1",
        _digest("0"),
        ResultStatus.SUCCEEDED,
        (evidence,),
        (finding,),
        (blocker,),
        (handoff,),
        ExecutionUsage(100, 40, 3, 2500),
        NOW,
    )
    verifier = VerifierRef(VerifierKind.SYSTEM, system_id="policy-verifier-v1")
    verification = ExecutionVerification(
        _scope(),
        "verification-1",
        "phase-1",
        "work-1",
        result.id,
        VerificationStatus.PASSED,
        _digest("1"),
        (VerificationCheck("tests.pass", True, (evidence.id,)),),
        verifier,
        NOW,
    )

    assert result.blockers[0].code == "approval.required"
    assert result.handoffs[0].target_profile == _profile()
    assert result.usage.cost_micros == 2500
    assert verification.verified_by == verifier
    with pytest.raises(ValueError, match="unknown evidence"):
        ExecutionResult(
            _scope(),
            "result-2",
            "phase-1",
            "work-1",
            "assignment-1",
            _digest("0"),
            ResultStatus.FAILED,
            (),
            (finding,),
            (),
            (),
            ExecutionUsage(0, 0, 0, 0),
            NOW,
        )


def test_contracts_reject_plain_enums_wrong_nested_types_and_duplicate_skill_names() -> None:
    with pytest.raises(TypeError, match="exact PhaseMode"):
        ExecutionPhase(
            _scope(),
            "phase-1",
            1,
            "research",
            _digest("1"),
            "read_only",
            _profile(),
            _skills(),
            1,
            (),
            RetryPolicy(),
            created_at=NOW,  # type: ignore[arg-type]
        )
    duplicate_name = (
        SkillVersionPin("research", "1", _digest("a")),
        SkillVersionPin("research", "2", _digest("b")),
    )
    with pytest.raises(ValueError, match="unique by name"):
        ExecutionAssignment(
            _scope(),
            "assignment-1",
            "phase-1",
            "work-1",
            "runtime-user-1",
            1,
            _profile(),
            duplicate_name,
            _authority(),
            created_at=NOW,
        )
    with pytest.raises(TypeError, match="exact ExecutionScopeRef"):
        ExecutionRootRun(
            object(),  # type: ignore[arg-type]
            _principal(),
            _digest("1"),
            _profile(),
            1,
            created_at=NOW,
        )


@pytest.mark.invariant("FR-RUN-20")
def test_lifecycle_matrices_and_terminal_metadata_fail_closed() -> None:
    assert can_transition_root_run(RootRunStatus.PENDING, RootRunStatus.RUNNING)
    assert can_transition_phase(ExecutionPhaseStatus.STARTING, ExecutionPhaseStatus.RUNNING)
    assert can_transition_work_item(LedgerWorkItemStatus.IN_FLIGHT, LedgerWorkItemStatus.VERIFYING)
    assert can_transition_assignment(AssignmentStatus.OFFERED, AssignmentStatus.CLAIMED)
    assert can_transition_verification(VerificationStatus.PENDING, VerificationStatus.PASSED)
    assert not can_transition_root_run(RootRunStatus.SUCCEEDED, RootRunStatus.RUNNING)
    assert not can_transition_phase(ExecutionPhaseStatus.FAILED, ExecutionPhaseStatus.STARTING)
    assert not can_transition_work_item(LedgerWorkItemStatus.DONE, LedgerWorkItemStatus.IN_FLIGHT)
    assert not can_transition_assignment(AssignmentStatus.COMPLETED, AssignmentStatus.RUNNING)
    assert not can_transition_verification(VerificationStatus.PASSED, VerificationStatus.PENDING)
    assert runtime_phase_status_value(ExecutionPhaseStatus.VERIFYING) == "running"
    assert all(
        not transitions.ROOT_RUN_TRANSITIONS[item]
        for item in (RootRunStatus.SUCCEEDED, RootRunStatus.FAILED, RootRunStatus.CANCELLED)
    )
    assert all(
        not transitions.PHASE_TRANSITIONS[item]
        for item in (
            ExecutionPhaseStatus.SUCCEEDED,
            ExecutionPhaseStatus.FAILED,
            ExecutionPhaseStatus.INTERRUPTED,
        )
    )
    assert all(
        not transitions.ASSIGNMENT_TRANSITIONS[item]
        for item in (
            AssignmentStatus.RELEASED,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.FAILED,
            AssignmentStatus.CANCELLED,
            AssignmentStatus.EXPIRED,
        )
    )
    assert all(
        not transitions.WORK_ITEM_TRANSITIONS[item]
        for item in (
            LedgerWorkItemStatus.DONE,
            LedgerWorkItemStatus.FAILED,
            LedgerWorkItemStatus.CANCELLED,
        )
    )
    assert all(
        not transitions.VERIFICATION_TRANSITIONS[item]
        for item in (
            VerificationStatus.PASSED,
            VerificationStatus.FAILED,
            VerificationStatus.NEEDS_REVISION,
        )
    )

    cancellation = CancellationMetadata(_principal(), "user.requested", NOW, _digest("6"))
    cancelled = ExecutionRootRun(
        _scope(),
        _principal(),
        _digest("2"),
        _profile(),
        7,
        RootRunStatus.CANCELLED,
        cancellation,
        created_at=NOW,
    )
    terminal = ExecutionPhase(
        _scope(),
        "phase-1",
        1,
        "research",
        _digest("3"),
        PhaseMode.READ_ONLY,
        _profile(),
        _skills(),
        7,
        (),
        RetryPolicy(),
        ExecutionPhaseStatus.SUCCEEDED,
        PhaseTerminalOutcome("completed", _digest("7"), NOW),
        created_at=NOW,
    )
    succeeded = ExecutionRootRun(
        _scope(),
        _principal(),
        _digest("2"),
        _profile(),
        7,
        RootRunStatus.SUCCEEDED,
        final_synthesis_digest=_digest("8"),
        created_at=NOW,
    )
    assert cancelled.cancellation == cancellation and terminal.terminal_outcome is not None
    assert succeeded.final_synthesis_digest == _digest("8")
    with pytest.raises(ValueError, match="requires cancellation"):
        ExecutionRootRun(
            _scope(),
            _principal(),
            _digest("2"),
            _profile(),
            7,
            RootRunStatus.CANCELLED,
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="final synthesis"):
        ExecutionRootRun(
            _scope(),
            _principal(),
            _digest("2"),
            _profile(),
            7,
            RootRunStatus.SUCCEEDED,
            created_at=NOW,
        )


@pytest.mark.invariant("SEC-153")
def test_runtime_identity_is_composite_scoped_and_contains_no_auth_state() -> None:
    identity = RuntimeIdentity("runtime-user-1", _principal(), _scope().workspace, created_at=NOW)
    names = {item.name for item in fields(RuntimeIdentity)}
    assert identity.principal.user_id == "user-1" and identity.engine_owner is EngineOwner.BOLTRIG
    assert not any(
        word in name
        for name in names
        for word in ("credential", "token", "secret", "path", "subject", "email")
    )
    with pytest.raises(ValueError, match="tenants differ"):
        RuntimeIdentity("runtime-user-2", _principal("org-2"), _scope().workspace, created_at=NOW)


@pytest.mark.invariant("SEC-153")
def test_fleet_and_ledger_share_one_exact_principal_and_phase_mode_vocabulary() -> None:
    assert FleetOrganisationUserRef is OrganisationUserRef
    assert FleetPhaseMode is PhaseMode
    principal = FleetOrganisationUserRef("org-1", "user-1")
    phase = PhaseRef("run-1", "phase-1", principal, "workspace-1")
    assert type(phase.principal) is OrganisationUserRef
    with pytest.raises(TypeError, match="exact OrganisationUserRef"):
        PhaseRef("run-1", "phase-1", object(), "workspace-1")  # type: ignore[arg-type]


def test_mutation_and_claim_outcomes_are_scoped_and_digest_bound() -> None:
    mutation = LedgerMutationOutcome(
        _scope(),
        "command-1",
        _digest("8"),
        LedgerMutationStatus.APPLIED,
        ExecutionAggregateKind.WORK_ITEM,
        "work-1",
        3,
        4,
    )
    claim = LedgerClaimOutcome(
        _scope(),
        "command-1",
        _digest("8"),
        LedgerClaimStatus.ACQUIRED,
        "work-1",
        "assignment-1",
        _lease(),
    )
    assert mutation.scope == claim.scope == _scope()
    with pytest.raises(ValueError, match="cannot issue"):
        LedgerClaimOutcome(
            _scope(),
            "command-1",
            _digest("8"),
            LedgerClaimStatus.HELD_BY_OTHER,
            "work-1",
            lease=_lease(),
        )
