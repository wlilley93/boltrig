"""Reusable behavior checks for the atomic, total attested-assignment admission.

The service is written against the ExecutionLedgerStore and
CapabilityAttestationStore Protocols, so the same matrix must hold over the
in-memory adapters and the durable PostgreSQL ones without a single change.
"""

from __future__ import annotations

import inspect

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
    LedgerMutationStatus,
)
from tests.unit.execution_ledger_fixtures import LedgerValues, NOW, digest
from tests.unit.execution_ledger_lifecycle_contract import seed_running_work

COMMAND_ID = "assign-work-a"
CATALOG_GENERATION = 2
VERBS = ("document.read", "ticket.read")


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
) -> AttestedAssignmentFacts:
    exact = values or LedgerValues()
    return AttestedAssignmentFacts(
        scope=exact.scope,
        assignment_id="assignment-1",
        phase_id="phase-a",
        work_item_id="work-a",
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
    "VERBS",
    "assert_admission_is_idempotent_on_replay",
    "assert_admission_mints_attests_and_persists",
    "assert_admission_offers_no_bypass_surface",
    "attestation",
    "authority",
    "facts",
]
