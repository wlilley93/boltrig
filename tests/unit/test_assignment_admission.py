"""Production memory-store attested-assignment admission tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from boltrig.fleet.application.assignment_admission import (
    AssignmentAdmission,
    AssignmentAdmissionRefused,
    AttestationEvidenceIncoherent,
)
from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
)
from boltrig.fleet.domain.grant_lease import GrantLeaseBinding
from boltrig.fleet.infrastructure.memory_capability_attestations import (
    MemoryCapabilityAttestationStore,
)
from boltrig.fleet.infrastructure.memory_execution_ledger import MemoryExecutionLedger
from boltrig.fleet.ports.capability_attestations import (
    CapabilityAttestationInsertResult,
    CapabilityAttestationInsertStatus,
)
from boltrig.fleet.ports.execution_ledger import AtomicLedgerWrite
from boltrig.models import (
    ExecutionAggregateKind,
    LedgerCommandKind,
    LedgerMutationOutcome,
    LedgerMutationStatus,
)
from tests.contracts.assignment_admission import (
    assert_admission_is_idempotent_on_replay,
    assert_admission_mints_attests_and_persists,
    assert_admission_offers_no_bypass_surface,
    authority,
    facts,
)
from tests.unit.execution_ledger_fixtures import CLOCK_NOW, LedgerValues, NOW, digest
from tests.unit.execution_ledger_lifecycle_contract import seed_running_work


def _build() -> tuple[AssignmentAdmission, MemoryCapabilityAttestationStore, MemoryExecutionLedger]:
    attestations = MemoryCapabilityAttestationStore()
    ledger = MemoryExecutionLedger(clock=lambda: CLOCK_NOW)
    return AssignmentAdmission(attestations, ledger), attestations, ledger


class _ReplayingAttestationStore(MemoryCapabilityAttestationStore):
    """A store whose retained set is not the submitted one, as a replay may be."""

    def __init__(self, retained: AssignmentCapabilityAttestationSet) -> None:
        super().__init__()
        self._retained = retained

    async def insert_once(
        self, attestations: AssignmentCapabilityAttestationSet
    ) -> CapabilityAttestationInsertResult:
        await super().insert_once(self._retained)
        return CapabilityAttestationInsertResult(
            CapabilityAttestationInsertStatus.REPLAYED, self._retained
        )


class _RefusingLedger(MemoryExecutionLedger):
    """A ledger that refuses the assignment, leaving whatever landed before it."""

    async def commit(self, write: AtomicLedgerWrite) -> LedgerMutationOutcome:
        if write.command.kind is not LedgerCommandKind.ASSIGN_WORK:
            return await super().commit(write)
        return LedgerMutationOutcome(
            write.command.scope,
            write.command.id,
            write.command.request_digest,
            LedgerMutationStatus.REJECTED,
            ExecutionAggregateKind.ASSIGNMENT,
            write.command.aggregate_id,
        )


def _minted(values: LedgerValues) -> AssignmentCapabilityAttestationSet:
    """The set a correct admission would mint for the default facts."""

    trusted = facts(values)
    return AssignmentCapabilityAttestationSet(
        binding=GrantLeaseBinding(
            values.tenant, values.workspace, values.run, "phase-a", "assignment-1"
        ),
        authority_evaluation_id=trusted.authority.id,
        authority_evaluation_digest=trusted.authority.digest,
        authority_policy_generation=trusted.authority.policy_generation,
        catalog_generation=trusted.catalog_generation,
        catalog_digest=trusted.catalog_digest,
        attestations=trusted.attestations,
    )


@pytest.mark.invariant("SEC-163")
async def test_admission_mints_attests_and_persists_one_assignment() -> None:
    admission, attestations, ledger = _build()
    await assert_admission_mints_attests_and_persists(admission, attestations, ledger)


@pytest.mark.invariant("SEC-163")
async def test_admitting_the_same_trusted_facts_twice_replays() -> None:
    admission, attestations, ledger = _build()
    await assert_admission_is_idempotent_on_replay(admission, attestations, ledger)


@pytest.mark.invariant("SEC-163")
async def test_admission_exposes_no_binding_pin_or_mint_only_bypass() -> None:
    admission, _, _ = _build()
    await assert_admission_offers_no_bypass_surface(admission)


@pytest.mark.invariant("SEC-163")
async def test_the_reference_carried_is_the_stores_retained_set_not_the_local_copy() -> None:
    values = LedgerValues()
    # A retained set that is valid, correctly bound, and NOT the submitted one:
    # exactly what a replay of history cut against another catalog generation is.
    retained = replace(_minted(values), catalog_generation=99)
    attestations = _ReplayingAttestationStore(retained)
    ledger = MemoryExecutionLedger(clock=lambda: CLOCK_NOW)
    admission = AssignmentAdmission(attestations, ledger)
    await seed_running_work(ledger, values, include_assignment=False)

    admitted = await admission.admit(facts(values))

    reference = admitted.attestation_set
    assert reference is not None
    assert reference.catalog_generation == 99, "the store's copy is authoritative"
    assert reference.attestation_set_digest == retained.digest
    pin = AssignmentCapabilityAttestationPin.from_assignment(admitted)
    assert pin is not None and pin.matches(retained)


@pytest.mark.invariant("SEC-163")
async def test_a_retained_set_the_assignment_cannot_name_fails_closed() -> None:
    values = LedgerValues()
    foreign = replace(
        _minted(values),
        binding=GrantLeaseBinding(
            values.tenant, values.workspace, values.run, "phase-a", "assignment-9"
        ),
    )
    attestations = _ReplayingAttestationStore(foreign)
    ledger = MemoryExecutionLedger(clock=lambda: CLOCK_NOW)
    admission = AssignmentAdmission(attestations, ledger)
    await seed_running_work(ledger, values, include_assignment=False)

    with pytest.raises(AttestationEvidenceIncoherent):
        await admission.admit(facts(values))

    assert await ledger.get_assignment(values.scope, "assignment-1") is None


@pytest.mark.invariant("SEC-163")
async def test_a_refused_ledger_leaves_an_orphaned_set_and_no_dangling_reference() -> None:
    values = LedgerValues()
    attestations = MemoryCapabilityAttestationStore()
    ledger = _RefusingLedger(clock=lambda: CLOCK_NOW)
    admission = AssignmentAdmission(attestations, ledger)
    await seed_running_work(ledger, values, include_assignment=False)

    with pytest.raises(AssignmentAdmissionRefused) as refusal:
        await admission.admit(facts(values))

    assert refusal.value.outcome.status is LedgerMutationStatus.REJECTED
    # The set landed first, so the residue is an orphan, never a reference to a
    # set that does not exist. An exact retry replays the orphan.
    stranded = await attestations.resolve_capability_attestations(
        AssignmentCapabilityAttestationPin.from_set(_minted(values))
    )
    assert stranded is not None


@pytest.mark.invariant("SEC-163")
async def test_evidence_that_disagrees_with_the_authority_evaluation_is_unconstructable() -> None:
    values = LedgerValues()
    trusted = facts(values)

    with pytest.raises(ValueError, match="attested verbs"):
        replace(trusted, attestations=trusted.attestations[:1])

    with pytest.raises(ValueError, match="attested verbs"):
        replace(trusted, authority=replace(authority(), permitted_verbs=("document.read",)))


@pytest.mark.invariant("SEC-163")
async def test_facts_reject_inexact_values() -> None:
    values = LedgerValues()
    trusted = facts(values)

    with pytest.raises(TypeError):
        replace(trusted, requested_at=NOW.isoformat())
    with pytest.raises(ValueError):
        replace(trusted, requested_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        replace(trusted, catalog_digest=digest("catalog").upper())
    with pytest.raises(ValueError):
        replace(trusted, catalog_generation=0)
    with pytest.raises(ValueError):
        replace(trusted, command_id="x" * 129)
    with pytest.raises(ValueError):
        replace(trusted, requested_by=replace(values.principal, tenant_id="other-org"))


@pytest.mark.invariant("SEC-163")
async def test_admit_rejects_anything_that_is_not_exact_trusted_facts() -> None:
    admission, _, _ = _build()

    with pytest.raises(TypeError):
        await admission.admit(object())  # type: ignore[arg-type]
