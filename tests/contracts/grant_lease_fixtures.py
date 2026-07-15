"""Deterministic records shared by GrantLeaseStore adapter contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from boltrig.fleet.domain.grant_lease import GrantLeaseBinding, StoredGrantLease
from boltrig.fleet.ports.grant_leases import GrantLeaseStore

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def binding(
    *,
    tenant: str = "tenant-1",
    workspace: str = "workspace-1",
    root: str = "root-1",
    phase: str = "phase-1",
    assignment: str = "assignment-1",
) -> GrantLeaseBinding:
    return GrantLeaseBinding(tenant, workspace, root, phase, assignment)


def lease(
    lease_id: str,
    *,
    scope: GrantLeaseBinding | None = None,
    generation: int = 1,
    issued_at: datetime = NOW,
    lifetime_seconds: int = 60,
    token_name: str | None = None,
) -> StoredGrantLease:
    token_digest = hashlib.sha256(
        (token_name or f"bearer-{lease_id}").encode("utf-8")
    ).hexdigest()
    return StoredGrantLease(
        lease_id=lease_id,
        binding=scope or binding(),
        token_digest=token_digest,
        permitted_verbs=("document.read", "ticket.read"),
        authority_evaluation_id=f"authority-{lease_id}",
        authority_evaluation_digest="sha256:" + "a" * 64,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=lifetime_seconds),
        max_ttl_seconds=lifetime_seconds,
        policy_generation=generation,
    )


async def attempt_insert(
    store: GrantLeaseStore, record: StoredGrantLease
) -> Exception | None:
    try:
        await store.insert_active(record, now=NOW)
    except Exception as exc:  # test helper records the exact concurrent outcome
        return exc
    return None


def foreign_bindings() -> tuple[GrantLeaseBinding, ...]:
    return (
        binding(tenant="tenant-2"),
        binding(workspace="workspace-2"),
        binding(root="root-2"),
        binding(phase="phase-2"),
        binding(assignment="assignment-2"),
    )


__all__ = ["NOW", "attempt_insert", "binding", "foreign_bindings", "lease"]
