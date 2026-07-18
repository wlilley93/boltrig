"""Pure and connection helpers for the durable capability-attestation adapter."""

from __future__ import annotations

import asyncpg

from boltrig.fleet.domain.capability_attestation import (
    AssignmentCapabilityAttestationSet,
    CapabilityAttestation,
    ConsequenceClassification,
    EffectClass,
)
from boltrig.fleet.domain.grant_lease import GrantLeaseBinding
from boltrig.models import Consequence

SET_COLS = (
    "tenant_id, workspace_id, root_run_id, phase_id, assignment_id, "
    "authority_evaluation_id, authority_evaluation_digest, authority_policy_generation, "
    "catalog_generation, catalog_digest, set_digest"
)

ENTRY_COLS = (
    "tenant_id, workspace_id, root_run_id, phase_id, assignment_id, "
    "verb_id, definition_digest, effect_class, consequence"
)

BINDING_WHERE = (
    "tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3 AND phase_id=$4 AND assignment_id=$5"
)


def binding_params(binding: GrantLeaseBinding) -> tuple[object, ...]:
    return (
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
        binding.phase_id,
        binding.assignment_id,
    )


async def lock_binding(conn: asyncpg.Connection, binding: GrantLeaseBinding) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext($1))",
        ":".join(
            (
                binding.tenant_id,
                binding.workspace_id,
                binding.root_run_id,
                binding.phase_id,
                binding.assignment_id,
            )
        ),
    )


async def stored_set_digest(
    conn: asyncpg.Connection, binding: GrantLeaseBinding
) -> str | None:
    return await conn.fetchval(
        f"SELECT set_digest FROM capability_attestation_sets WHERE {BINDING_WHERE}",
        *binding_params(binding),
    )


async def load_set(
    conn: asyncpg.Connection, binding: GrantLeaseBinding
) -> AssignmentCapabilityAttestationSet | None:
    header = await conn.fetchrow(
        f"SELECT {SET_COLS} FROM capability_attestation_sets WHERE {BINDING_WHERE}",
        *binding_params(binding),
    )
    if header is None:
        return None
    entries = await conn.fetch(
        f"SELECT {ENTRY_COLS} FROM capability_attestation_entries WHERE {BINDING_WHERE}",
        *binding_params(binding),
    )
    attestations = tuple(
        CapabilityAttestation(
            verb_id=row["verb_id"],
            definition_digest=row["definition_digest"],
            classification=ConsequenceClassification(
                EffectClass(row["effect_class"]),
                Consequence(row["consequence"]),
            ),
        )
        for row in entries
    )
    return AssignmentCapabilityAttestationSet(
        binding=binding,
        authority_evaluation_id=header["authority_evaluation_id"],
        authority_evaluation_digest=header["authority_evaluation_digest"],
        authority_policy_generation=header["authority_policy_generation"],
        catalog_generation=header["catalog_generation"],
        catalog_digest=header["catalog_digest"],
        attestations=attestations,
    )


async def insert_set(
    conn: asyncpg.Connection, attestations: AssignmentCapabilityAttestationSet
) -> None:
    binding = attestations.binding
    await conn.execute(
        f"INSERT INTO capability_attestation_sets ({SET_COLS}) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        *binding_params(binding),
        attestations.authority_evaluation_id,
        attestations.authority_evaluation_digest,
        attestations.authority_policy_generation,
        attestations.catalog_generation,
        attestations.catalog_digest,
        attestations.digest,
    )
    if attestations.attestations:
        await conn.executemany(
            f"INSERT INTO capability_attestation_entries ({ENTRY_COLS}) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            [
                (
                    *binding_params(binding),
                    item.verb_id,
                    item.definition_digest,
                    item.classification.effect_class.value,
                    item.classification.consequence.value,
                )
                for item in attestations.attestations
            ],
        )


__all__ = [
    "BINDING_WHERE",
    "ENTRY_COLS",
    "SET_COLS",
    "binding_params",
    "insert_set",
    "load_set",
    "lock_binding",
    "stored_set_digest",
]
