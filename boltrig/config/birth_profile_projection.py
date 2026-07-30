"""Public projection of retained, secret-free birth-profile receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boltrig.models import (
    BIRTH_PROFILE_MAX_RETURNED_RECEIPTS,
    BIRTH_PROFILE_PROCESS_KINDS,
    BIRTH_PROFILE_RECEIPTS_PER_PROCESS,
    BirthProfileReceipt,
    utcnow,
)

_IDENTITY_FIELDS = (
    "manifest_generation",
    "addon_set_identity",
    "codex_provider_identity",
    "sensitive_role_identity",
)


def _public_receipt(
    receipt: BirthProfileReceipt,
    *,
    reference: BirthProfileReceipt | None,
    now: datetime,
) -> dict[str, Any]:
    stale = now >= receipt.expires_at
    mismatches = (
        []
        if reference is None
        else [
            field
            for field in _IDENTITY_FIELDS
            if getattr(receipt, field) != getattr(reference, field)
        ]
    )
    if stale:
        evidence_state = "stale_startup_liveness_unknown"
    elif reference is None:
        evidence_state = "startup_observed_reference_unavailable"
    elif mismatches:
        evidence_state = "mismatched_startup_liveness_unknown"
    else:
        evidence_state = "matched_reference_liveness_unknown"
    return {
        "process_kind": receipt.process_kind,
        "instance_identity": receipt.instance_identity,
        "evidence_state": evidence_state,
        "reason": None,
        "matches_reference": None if reference is None else not mismatches,
        "mismatches": mismatches,
        "manifest_generation": receipt.manifest_generation,
        "addon_set_identity": receipt.addon_set_identity,
        "codex_provider_identity": receipt.codex_provider_identity,
        "codex_provider_state": receipt.codex_provider_state,
        "sensitive_role_identity": receipt.sensitive_role_identity,
        "sensitive_role_state": receipt.sensitive_role_state,
        "receipt_kind": receipt.receipt_kind,
        "observed_at": receipt.observed_at.isoformat(),
        "expires_at": receipt.expires_at.isoformat(),
        "liveness_claimed": False,
    }


def _missing_observation(process_kind: str) -> dict[str, Any]:
    return {
        "process_kind": process_kind,
        "instance_identity": None,
        "evidence_state": "unavailable",
        "reason": "no_startup_receipt",
        "matches_reference": None,
        "mismatches": [],
        "manifest_generation": None,
        "addon_set_identity": None,
        "codex_provider_identity": None,
        "codex_provider_state": "unavailable",
        "sensitive_role_identity": None,
        "sensitive_role_state": "unavailable",
        "receipt_kind": None,
        "observed_at": None,
        "expires_at": None,
        "liveness_claimed": False,
    }


def _reference_view(
    reference: BirthProfileReceipt | None, current: datetime
) -> dict[str, Any]:
    if reference is None:
        return {
            "status": "unavailable",
            "source_process": "api",
            "reason": "api_startup_receipt_unavailable",
            "basis": "latest_api_startup_receipt",
            "instance_identity": None,
            "manifest_generation": None,
            "addon_set_identity": None,
            "codex_provider_identity": None,
            "codex_provider_state": "unavailable",
            "sensitive_role_identity": None,
            "sensitive_role_state": "unavailable",
            "observed_at": None,
            "expires_at": None,
            "liveness_claimed": False,
        }
    return {
        "status": (
            "stale_startup_liveness_unknown"
            if current >= reference.expires_at
            else "startup_snapshot_liveness_unknown"
        ),
        "source_process": "api",
        "reason": None,
        "basis": "latest_api_startup_receipt",
        "instance_identity": reference.instance_identity,
        "manifest_generation": reference.manifest_generation,
        "addon_set_identity": reference.addon_set_identity,
        "codex_provider_identity": reference.codex_provider_identity,
        "codex_provider_state": reference.codex_provider_state,
        "sensitive_role_identity": reference.sensitive_role_identity,
        "sensitive_role_state": reference.sensitive_role_state,
        "observed_at": reference.observed_at.isoformat(),
        "expires_at": reference.expires_at.isoformat(),
        "liveness_claimed": False,
    }


async def birth_profile_view(
    store: Any,
    tenant_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compare all retained startup snapshots with the latest API reference."""

    current = now or utcnow()
    rows = await store.list_birth_profile_receipts(tenant_id)
    by_kind = {
        process_kind: [row for row in rows if row.process_kind == process_kind]
        for process_kind in BIRTH_PROFILE_PROCESS_KINDS
    }
    api_rows = by_kind["api"]
    reference = max(api_rows, key=lambda row: row.observed_at) if api_rows else None
    observations = [
        observation
        for process_kind in BIRTH_PROFILE_PROCESS_KINDS
        for observation in (
            [
                _public_receipt(row, reference=reference, now=current)
                for row in by_kind[process_kind]
            ]
            or [_missing_observation(process_kind)]
        )
    ]
    mismatch_count = sum(item["matches_reference"] is False for item in observations)
    stale_count = sum(
        item["evidence_state"] == "stale_startup_liveness_unknown"
        for item in observations
    )
    unavailable_count = sum(
        item["evidence_state"] == "unavailable" for item in observations
    )
    if reference is None:
        status = "reference_unavailable"
    elif mismatch_count:
        status = "observed_mismatch"
    elif unavailable_count:
        status = "process_kind_unavailable"
    elif stale_count:
        status = "stale_startup_evidence"
    else:
        status = "startup_profiles_match_reference_liveness_unknown"
    return {
        "tenant_id": tenant_id,
        "status": status,
        "reference": _reference_view(reference, current),
        "observations": observations,
        "summary": {
            "mismatch_count": mismatch_count,
            "stale_count": stale_count,
            "unavailable_count": unavailable_count,
            "retained_instance_count": len(rows),
            "max_retained_instances_per_process": BIRTH_PROFILE_RECEIPTS_PER_PROCESS,
            "max_returned_instances": BIRTH_PROFILE_MAX_RETURNED_RECEIPTS,
            "liveness_claimed": False,
            "replica_coverage_claimed": False,
        },
    }
