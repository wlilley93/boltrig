"""Deterministic records shared by GrantLeaseStore adapter contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseCandidate,
    StoredGrantLease,
)
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from boltrig.models import (
    AttestationSetRef,
    AuthorityEvaluationRef,
    ExecutionAssignment,
    ExecutionScopeRef,
    ProfileVersionPin,
    WorkspaceScopeRef,
)

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
    authority: GrantAuthoritySnapshot | None = None,
    issue_operation_id: str | None = None,
    expected_current_lease_generation: int | None = None,
    issued_at: datetime = NOW,
    lifetime_seconds: int = 60,
    token_name: str | None = None,
) -> GrantLeaseCandidate:
    exact_scope = scope or (authority.binding if authority is not None else binding())
    exact_authority = authority or authority_snapshot(scope=exact_scope)
    token_digest = hashlib.sha256((token_name or f"bearer-{lease_id}").encode("utf-8")).hexdigest()
    return GrantLeaseCandidate(
        lease_id=lease_id,
        issue_operation_id=issue_operation_id or f"issue-{lease_id}",
        binding=exact_scope,
        token_digest=token_digest,
        authority_snapshot=exact_authority,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=lifetime_seconds),
        max_ttl_seconds=lifetime_seconds,
        expected_current_lease_generation=expected_current_lease_generation,
    )


def assignment(
    *,
    scope: GrantLeaseBinding | None = None,
    authority_evaluation_id: str = "authority-1",
    authority_evaluation_digest: str = "sha256:" + "a" * 64,
    authority_policy_generation: int = 1,
    permitted_verbs: tuple[str, ...] = ("document.read", "ticket.read"),
    attestation_set: AttestationSetRef | None = None,
) -> ExecutionAssignment:
    """Build the canonical record every grant-scope value is projected from."""

    exact_scope = scope or binding()
    return ExecutionAssignment(
        scope=ExecutionScopeRef(
            WorkspaceScopeRef(exact_scope.tenant_id, exact_scope.workspace_id),
            exact_scope.root_run_id,
        ),
        id=exact_scope.assignment_id,
        phase_id=exact_scope.phase_id,
        work_item_id=f"work-{exact_scope.assignment_id}",
        runtime_identity_id=f"runtime-{exact_scope.assignment_id}",
        attempt=1,
        profile=ProfileVersionPin(
            "grant-test-profile",
            "1",
            "sha256:" + "c" * 64,
        ),
        skills=(),
        authority=AuthorityEvaluationRef(
            authority_evaluation_id,
            authority_evaluation_digest,
            authority_policy_generation,
            permitted_verbs,
            NOW,
        ),
        attestation_set=attestation_set,
        created_at=NOW,
    )


def authority_snapshot(
    *,
    scope: GrantLeaseBinding | None = None,
    authority_evaluation_id: str = "authority-1",
    authority_evaluation_digest: str = "sha256:" + "a" * 64,
    authority_policy_generation: int = 1,
    permitted_verbs: tuple[str, ...] = ("document.read", "ticket.read"),
) -> GrantAuthoritySnapshot:
    return GrantAuthoritySnapshot.from_execution_assignment(
        assignment(
            scope=scope,
            authority_evaluation_id=authority_evaluation_id,
            authority_evaluation_digest=authority_evaluation_digest,
            authority_policy_generation=authority_policy_generation,
            permitted_verbs=permitted_verbs,
        )
    )


async def attempt_insert(
    store: GrantLeaseStore,
    record: GrantLeaseCandidate,
    *,
    expected_authority: GrantAuthoritySnapshot | None = None,
    now: datetime = NOW,
) -> StoredGrantLease | Exception:
    try:
        return await store.insert_active(
            record,
            expected_authority=expected_authority or record.authority_snapshot,
            now=now,
        )
    except Exception as exc:  # test helper records the exact concurrent outcome
        return exc


def foreign_bindings() -> tuple[GrantLeaseBinding, ...]:
    return (
        binding(tenant="tenant-2"),
        binding(workspace="workspace-2"),
        binding(root="root-2"),
        binding(phase="phase-2"),
        binding(assignment="assignment-2"),
    )


__all__ = [
    "NOW",
    "assignment",
    "attempt_insert",
    "authority_snapshot",
    "binding",
    "foreign_bindings",
    "lease",
]
