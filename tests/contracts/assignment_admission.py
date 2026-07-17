"""Reusable behavior checks for the atomic, total attested-assignment admission.

The service is written against the ExecutionLedgerStore and
CapabilityAttestationStore Protocols, so the same matrix must hold over the
in-memory adapters and the durable PostgreSQL ones without a single change.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace

from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.domain.attested_assignment import AttestedAssignmentFacts
from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationPin,
    CapabilityAttestation,
    ConsequenceClassification,
    EffectClass,
)
from boltrig.fleet.domain.grant_lease import GrantLeaseBinding
from boltrig.fleet.ports.capability_attestations import CapabilityAttestationStore
from boltrig.fleet.ports.execution_ledger import ExecutionLedgerStore
from boltrig.models import (
    AuthorityEvaluationRef,
    Consequence,
    ExecutionScopeRef,
    LedgerCommandKind,
    LedgerMutationStatus,
    RecordedExecutionEvent,
)
from tests.unit.execution_ledger_fixtures import LedgerValues, NOW, digest
from tests.unit.execution_ledger_lifecycle_contract import seed_running_work

COMMAND_ID = "assign-work-a"
CATALOG_GENERATION = 2
VERBS = ("document.read", "ticket.read")
# Mirrors the root-admission race precedent's N so the two proofs contend alike.
RACE_CALLERS = 64


def attestation(verb_id: str) -> CapabilityAttestation:
    return CapabilityAttestation(
        verb_id=verb_id,
        definition_digest=digest(f"definition-{verb_id}"),
        classification=ConsequenceClassification(
            EffectClass.READ_ONLY_NO_EXTERNAL_EFFECT, Consequence.LOW
        ),
    )


def authority(*, policy_generation: int = 3) -> AuthorityEvaluationRef:
    return AuthorityEvaluationRef(
        "authority-a",
        digest("authority"),
        policy_generation,
        VERBS,
        NOW,
    )


def facts(
    values: LedgerValues | None = None,
    *,
    command_id: str = COMMAND_ID,
    catalog_generation: int = CATALOG_GENERATION,
    assignment_id: str = "assignment-1",
    work_item_id: str = "work-a",
) -> AttestedAssignmentFacts:
    exact = values or LedgerValues()
    return AttestedAssignmentFacts(
        scope=exact.scope,
        assignment_id=assignment_id,
        phase_id="phase-a",
        work_item_id=work_item_id,
        runtime_identity_id="runtime-a",
        profile=exact.profile,
        skills=exact.skills,
        authority=authority(),
        attestations=tuple(attestation(verb) for verb in VERBS),
        catalog_generation=catalog_generation,
        catalog_digest=digest("catalog"),
        requested_by=exact.principal,
        command_id=command_id,
        requested_at=NOW,
    )


async def assert_admission_mints_attests_and_persists(
    admission: AssignmentAdmission,
    attestations: CapabilityAttestationStore,
    ledger: ExecutionLedgerStore,
) -> None:
    """One admission yields a committed assignment whose evidence resolves."""

    values = LedgerValues()
    await seed_running_work(ledger, values, include_assignment=False)

    admitted = await admission.admit(facts(values))

    reference = admitted.attestation_set
    assert reference is not None, "an admitted assignment always names its evidence"
    assert reference.catalog_generation == CATALOG_GENERATION

    # The evidence is reachable from the record alone: no binding, no authority,
    # and no digest is supplied by this test to find it.
    pin = AssignmentCapabilityAttestationPin.from_assignment(admitted)
    assert pin is not None
    retained = await attestations.resolve_capability_attestations(pin)
    assert retained is not None, "the attestation set landed before the assignment"
    assert pin.matches(retained)
    assert retained.digest == reference.attestation_set_digest

    # The minted set's binding is the one derived from the final record.
    assert retained.binding == GrantLeaseBinding.from_execution_assignment(admitted)
    assert retained.verb_ids == admitted.authority.permitted_verbs
    assert retained.authority_evaluation_id == admitted.authority.id
    assert retained.authority_evaluation_digest == admitted.authority.digest
    assert retained.authority_policy_generation == admitted.authority.policy_generation

    stored = await ledger.get_assignment(values.scope, "assignment-1")
    assert stored == admitted, "the ledger holds exactly the returned record"

    outcome = await ledger.get_command_outcome(values.scope, COMMAND_ID)
    assert outcome is not None and outcome.status is LedgerMutationStatus.APPLIED


async def assert_admission_is_idempotent_on_replay(
    admission: AssignmentAdmission,
    attestations: CapabilityAttestationStore,
    ledger: ExecutionLedgerStore,
) -> None:
    """The same trusted facts admitted twice replay; they never conflict."""

    values = LedgerValues()
    await seed_running_work(ledger, values, include_assignment=False)

    first = await admission.admit(facts(values))
    second = await admission.admit(facts(values))

    assert second == first, "an exact re-admission is the same record"
    stored = await ledger.get_assignment(values.scope, "assignment-1")
    assert stored == first

    # Exactly one attestation set and one assignment exist: the set replayed
    # rather than conflicting, and so did the ledger command.
    pin = AssignmentCapabilityAttestationPin.from_assignment(second)
    assert pin is not None
    assert await attestations.resolve_capability_attestations(pin) is not None

    events = await ledger.list_events(values.scope)
    created = tuple(
        item for item in events if item.pending.causation_command_id == COMMAND_ID
    )
    assert len(created) == 1, "a replay appends no second event"


async def _every_event(
    ledger: ExecutionLedgerStore, scope: ExecutionScopeRef
) -> tuple[RecordedExecutionEvent, ...]:
    """Page the whole event history for a scope.

    ``list_events`` is a paged read defaulting to 100 events, and a 64-way race on
    top of the seeded lifecycle overruns that.  Counting the first page only would
    silently under-count and turn a duplicate-event defect into a passing test.
    """

    collected: list[RecordedExecutionEvent] = []
    after = 0
    while page := await ledger.list_events(scope, after_sequence=after, limit=100):
        collected.extend(page)
        after = page[-1].sequence
    return tuple(collected)


async def _seed_racing_work_items(
    ledger: ExecutionLedgerStore,
    values: LedgerValues,
    identifiers: tuple[str, ...],
) -> None:
    """Enqueue one PENDING work item per racer, so each has something of its own."""

    template = values.work()
    for ordinal, item in enumerate(identifiers, start=2):
        work = replace(template, id=f"work-{item}", ordinal=ordinal)
        outcome = await ledger.commit(
            values.write(
                work,
                LedgerCommandKind.ENQUEUE_WORK,
                expected_version=0,
                command_id=f"{values.run}-create-{work.id}",
            )
        )
        assert outcome.status is LedgerMutationStatus.APPLIED


async def assert_concurrent_identical_admissions_are_coherent(
    admission: AssignmentAdmission,
    attestations: CapabilityAttestationStore,
    ledger: ExecutionLedgerStore,
) -> None:
    """The fused two-store path is total and coherent under a same-command race.

    The service holds no lock of its own and no transaction spans its two stores,
    so the only thing standing between N callers and a torn record is that each
    store serializes its own writes and that the service derives everything it
    persists from what the store retained.  Racing the identical trusted facts is
    what proves that composition, because every caller mints the same set, names
    the same binding, and submits the byte-identical ledger command.
    """

    values = LedgerValues()
    await seed_running_work(ledger, values, include_assignment=False)

    # No return_exceptions: a deadlock between the attestation store's per-binding
    # lock domain and the ledger's workspace/scope domain surfaces as an
    # asyncpg DeadlockDetectedError, and it must fail this test rather than be
    # counted as one more refusal.
    admitted = await asyncio.gather(
        *(admission.admit(facts(values)) for _ in range(RACE_CALLERS))
    )

    # One coherent outcome: not "mostly the same", exactly one record.
    assert len(admitted) == RACE_CALLERS
    winner = admitted[0]
    assert all(item == winner for item in admitted), "callers disagree on the record"

    # The set replayed rather than conflicting, and it is the set the record names.
    reference = winner.attestation_set
    assert reference is not None
    pin = AssignmentCapabilityAttestationPin.from_assignment(winner)
    assert pin is not None
    retained = await attestations.resolve_capability_attestations(pin)
    assert retained is not None, "the one retained set is the one the record names"
    assert retained.digest == reference.attestation_set_digest
    assert retained.binding == GrantLeaseBinding.from_execution_assignment(winner)

    # The ledger holds exactly the record every caller was handed, not a torn one.
    stored = await ledger.get_assignment(values.scope, winner.id)
    assert stored == winner

    # The command replayed rather than duplicating: one APPLIED outcome, one event.
    outcome = await ledger.get_command_outcome(values.scope, COMMAND_ID)
    assert outcome is not None and outcome.status is LedgerMutationStatus.APPLIED
    events = await _every_event(ledger, values.scope)
    created = tuple(
        item for item in events if item.pending.causation_command_id == COMMAND_ID
    )
    assert len(created) == 1, f"a race appended {len(created)} events, not one"

    # Totality survives the race: a later sequential admit still replays it.
    assert await admission.admit(facts(values)) == winner


async def assert_concurrent_distinct_admissions_are_total(
    admission: AssignmentAdmission,
    attestations: CapabilityAttestationStore,
    ledger: ExecutionLedgerStore,
) -> None:
    """Distinct assignments racing in one scope all land, and nothing deadlocks.

    This is the sharper case for the durable adapters.  Each caller takes the
    attestation store's per-binding lock (uncontended, the bindings differ) and
    then the ledger's workspace-shared plus scope-exclusive locks (contended, the
    scope is shared) in two separate transactions.  Two lock domains taken in
    sequence by N racers is the shape that produces surprises, so every caller
    must still get its own APPLIED record with its own evidence behind it.

    Each racer assigns its OWN work item.  One live assignment per work item is a
    ledger rule (``_validate_attempt``), so racing N assignments at one work item
    would prove nothing about locking: it would just be N-1 lawful conflicts.
    """

    values = LedgerValues()
    await seed_running_work(ledger, values, include_assignment=False)

    identifiers = tuple(f"assignment-{index}" for index in range(RACE_CALLERS))
    await _seed_racing_work_items(ledger, values, identifiers)
    admitted = await asyncio.gather(
        *(
            admission.admit(
                facts(
                    values,
                    command_id=f"{COMMAND_ID}-{item}",
                    assignment_id=item,
                    work_item_id=f"work-{item}",
                )
            )
            for item in identifiers
        )
    )

    # Every racer got its own record: none was serialized into another's identity.
    assert tuple(item.id for item in admitted) == identifiers
    assert len({item.id for item in admitted}) == RACE_CALLERS

    for record in admitted:
        # No set is retained under one binding while the assignment names another.
        pin = AssignmentCapabilityAttestationPin.from_assignment(record)
        assert pin is not None
        retained = await attestations.resolve_capability_attestations(pin)
        assert retained is not None, f"{record.id} lost its evidence in the race"
        assert retained.binding == GrantLeaseBinding.from_execution_assignment(record)
        reference = record.attestation_set
        assert reference is not None
        assert retained.digest == reference.attestation_set_digest

        stored = await ledger.get_assignment(values.scope, record.id)
        assert stored == record, f"{record.id} is not the record the ledger holds"

        outcome = await ledger.get_command_outcome(values.scope, f"{COMMAND_ID}-{record.id}")
        assert outcome is not None and outcome.status is LedgerMutationStatus.APPLIED

    events = await _every_event(ledger, values.scope)
    causes = {f"{COMMAND_ID}-{item}" for item in identifiers}
    created = tuple(
        item for item in events if item.pending.causation_command_id in causes
    )
    assert len(created) == RACE_CALLERS, "one event per distinct admission, no more"
    # Every racer's event is separately sequenced: the race tore no sequence.
    assert len({item.sequence for item in created}) == RACE_CALLERS


async def assert_admission_offers_no_bypass_surface(
    admission: AssignmentAdmission,
) -> None:
    """Structural, not behavioural: the caller has nowhere to inject evidence.

    A value assertion alone would pass straight through a seam that merely
    DEFAULTS to the derived value, so the absence of the seam is asserted on the
    signature itself.
    """

    public = tuple(
        name
        for name in dir(admission)
        if not name.startswith("_") and callable(getattr(admission, name))
    )
    assert public == ("admit",), "admission exposes exactly one verb"

    parameters = inspect.signature(admission.admit).parameters
    assert tuple(parameters) == ("facts",), "admit takes trusted facts and nothing else"
    assert parameters["facts"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["facts"].default is inspect.Parameter.empty

    # The trusted facts themselves cannot carry evidence either: the fields that
    # would let a caller name another assignment's set simply do not exist.
    fields = tuple(inspect.signature(AttestedAssignmentFacts).parameters)
    forbidden = ("binding", "pin", "attestation_set", "attestation_set_digest", "attempt")
    assert not set(fields) & set(forbidden), f"facts must not carry evidence: {fields}"


__all__ = [
    "CATALOG_GENERATION",
    "COMMAND_ID",
    "RACE_CALLERS",
    "VERBS",
    "assert_admission_is_idempotent_on_replay",
    "assert_admission_mints_attests_and_persists",
    "assert_admission_offers_no_bypass_surface",
    "assert_concurrent_distinct_admissions_are_total",
    "assert_concurrent_identical_admissions_are_coherent",
    "attestation",
    "authority",
    "facts",
]
