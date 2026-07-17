"""Governed admission that fuses attestation minting with ledger persistence."""

from __future__ import annotations

from dataclasses import replace

from boltrig.fleet.domain.attested_assignment import AttestedAssignmentFacts
from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    AssignmentCapabilityAttestationSet,
)
from boltrig.fleet.domain.grant_lease import GrantLeaseBinding
from boltrig.fleet.ports.capability_attestations import CapabilityAttestationStore
from boltrig.fleet.ports.execution_ledger import (
    AtomicLedgerWrite,
    ExecutionLedgerStore,
    OutboxIntent,
)
from boltrig.models import (
    AttestationSetRef,
    CanonicalEventPayload,
    EngineOwner,
    ExecutionAggregateKind,
    ExecutionAssignment,
    ExecutionEventKind,
    LedgerCommand,
    LedgerCommandKind,
    LedgerMutationOutcome,
    LedgerMutationStatus,
    NormalizedExecutionMetadata,
    PendingExecutionEvent,
)

_OUTBOX_DESTINATION = "execution.timeline"
_FIRST_ATTEMPT = 1
_CREATE_EXPECTED_VERSION = 0
_COMMITTED = frozenset({LedgerMutationStatus.APPLIED, LedgerMutationStatus.REPLAYED})


class AssignmentAdmissionError(RuntimeError):
    """An assignment could not be admitted without weakening durable history."""


class AttestationEvidenceIncoherent(AssignmentAdmissionError):
    """The retained attestation set is not the set this assignment's pin names."""


class AssignmentAdmissionRefused(AssignmentAdmissionError):
    """The canonical ledger refused the assignment; nothing was committed."""

    __slots__ = ("outcome",)

    def __init__(self, outcome: LedgerMutationOutcome) -> None:
        super().__init__(f"assignment admission was refused: {outcome.status.value}")
        self.outcome = outcome


class AssignmentAdmission:
    """The sole atomic, total path from trusted facts to an attested assignment.

    An assignment never reaches the ledger on unattested evidence: minting the
    capability-attestation set, retaining it insert-once, and committing the
    assignment that names it are one operation.  There is no mint-only surface,
    no attest-later surface, and no surface that commits an assignment without a
    retained set behind it.

    The two stores are separate and share no transaction, so one of them lands
    first.  The set is minted and retained FIRST, then the assignment is
    committed.  An orphaned set is benign: it is immutable, insert-once, keyed by
    a binding that no assignment references, and therefore unreachable, and an
    exact retry replays it rather than conflicting with it.  A dangling reference
    is not benign: an assignment naming a set that does not exist is a record
    whose evidence can never be resolved.  The order fails toward the harmless
    residue.

    Per the pin ratio, the binding is DERIVED from the assignment record by
    ``GrantLeaseBinding.from_execution_assignment`` and is never assembled from
    loose identifiers, and the reference the assignment carries is built from the
    digests of the set the store RETAINED, never from the local copy that was
    submitted to it.
    """

    __slots__ = ("_attestations", "_ledger")

    def __init__(
        self,
        attestations: CapabilityAttestationStore,
        ledger: ExecutionLedgerStore,
    ) -> None:
        # Both dependencies are Protocols exercised through their own contracts,
        # so they are bound rather than type-checked; the memory and PostgreSQL
        # adapters are interchangeable here by construction.
        self._attestations = attestations
        self._ledger = ledger

    def __repr__(self) -> str:
        return "AssignmentAdmission()"

    async def admit(self, facts: AttestedAssignmentFacts) -> ExecutionAssignment:
        """Persist exactly one attested assignment per command, or replay it verbatim."""
        if type(facts) is not AttestedAssignmentFacts:
            raise TypeError("facts must be an exact AttestedAssignmentFacts")
        unattested = _assignment(facts)
        retained = await self._retain(unattested, facts)
        assignment = replace(
            unattested,
            attestation_set=AttestationSetRef(
                catalog_generation=retained.catalog_generation,
                catalog_digest=retained.catalog_digest,
                attestation_set_digest=retained.digest,
            ),
        )
        # Derived from the finished record and nothing else. A store that retained
        # a set this assignment cannot name (a divergent replay, a hostile adapter)
        # fails closed here rather than producing a record whose own pin misses.
        pin = AssignmentCapabilityAttestationPin.from_assignment(assignment)
        if pin is None or not pin.matches(retained):
            raise AttestationEvidenceIncoherent(
                "retained attestation set is not the set this assignment names"
            )
        outcome = await self._ledger.commit(_write(assignment, facts))
        if outcome.status not in _COMMITTED:
            raise AssignmentAdmissionRefused(outcome)
        return assignment

    async def _retain(
        self,
        assignment: ExecutionAssignment,
        facts: AttestedAssignmentFacts,
    ) -> AssignmentCapabilityAttestationSet:
        """Mint against the record's own derived binding and return the store's set."""
        authority = assignment.authority
        minted = AssignmentCapabilityAttestationSet(
            binding=GrantLeaseBinding.from_execution_assignment(assignment),
            authority_evaluation_id=authority.id,
            authority_evaluation_digest=authority.digest,
            authority_policy_generation=authority.policy_generation,
            catalog_generation=facts.catalog_generation,
            catalog_digest=facts.catalog_digest,
            attestations=facts.attestations,
        )
        result = await self._attestations.insert_once(minted)
        # On REPLAYED the store's copy is the authoritative one; on INSERTED it is
        # this one. Taking the result's set unconditionally removes the difference.
        return result.attestations


def _assignment(facts: AttestedAssignmentFacts) -> ExecutionAssignment:
    """Build the first, unattested attempt; the set reference is not known yet."""

    return ExecutionAssignment(
        facts.scope,
        facts.assignment_id,
        facts.phase_id,
        facts.work_item_id,
        facts.runtime_identity_id,
        _FIRST_ATTEMPT,
        facts.profile,
        facts.skills,
        facts.authority,
        attestation_set=None,
        created_at=facts.requested_at,
    )


def _write(assignment: ExecutionAssignment, facts: AttestedAssignmentFacts) -> AtomicLedgerWrite:
    """Compose the ASSIGN_WORK write, deriving every identifier from the command id.

    Derivation, rather than synthesis, is what makes an exact re-admission of the
    same trusted facts a byte-identical write and therefore a ledger replay.
    """

    command = LedgerCommand.create(
        id=facts.command_id,
        kind=LedgerCommandKind.ASSIGN_WORK,
        scope=facts.scope,
        aggregate_kind=ExecutionAggregateKind.ASSIGNMENT,
        aggregate_id=assignment.id,
        expected_version=_CREATE_EXPECTED_VERSION,
        parameters=(),
        issued_by=facts.requested_by,
        issued_at=facts.requested_at,
    )
    event = PendingExecutionEvent(
        f"event-{facts.command_id}",
        facts.scope,
        ExecutionAggregateKind.ASSIGNMENT,
        assignment.id,
        ExecutionEventKind.CREATED,
        f"ingest-{facts.command_id}",
        facts.scope.root_run_id,
        CanonicalEventPayload.from_metadata(
            NormalizedExecutionMetadata(status=assignment.status.value)
        ),
        EngineOwner.BOLTRIG,
        command.id,
        occurred_at=facts.requested_at,
    )
    intent = OutboxIntent(
        f"outbox-{facts.command_id}",
        _OUTBOX_DESTINATION,
        f"deliver-{facts.command_id}",
        facts.requested_at,
    )
    return AtomicLedgerWrite(command, assignment, event, (intent,))


__all__ = [
    "AssignmentAdmission",
    "AssignmentAdmissionError",
    "AssignmentAdmissionRefused",
    "AttestationEvidenceIncoherent",
]
