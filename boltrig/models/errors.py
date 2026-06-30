"""The kernel error taxonomy.

These map 1:1 to the dispatch contract (S7.1) and are the only ways a verb
invocation can fail. ``PendingHuman`` and ``DegradedMode`` are control-flow
signals, not failures: they carry a result the caller acts on.
"""

from __future__ import annotations

from typing import Any


class BoltrigError(Exception):
    """Base for every kernel-raised error."""

    status_code: int = 500
    reason: str = "internal_error"


class SchemaValidationError(BoltrigError):
    """Verb params (or output) did not match the registered JSON Schema (SEC-21)."""

    status_code = 400
    reason = "schema_invalid"

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class BindingNotFound(BoltrigError):
    """No verb_binding resolves this verb for this tenant (fail-closed, K-13)."""

    status_code = 404
    reason = "binding_not_found"


class GrantMissing(BoltrigError):
    """The caller's grants do not authorise this verb (P8, SEC-07, K-2)."""

    status_code = 403
    reason = "grant_missing"


class TenantIsolation(BoltrigError):
    """A cross-tenant access was attempted (SEC-08, K-22)."""

    status_code = 403
    reason = "tenant_isolation"


class RateLimited(BoltrigError):
    """A per-verb / per-tenant rate limit was hit (FR-KER-05)."""

    status_code = 429
    reason = "rate_limited"

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class BudgetExceeded(BoltrigError):
    """A token/cost budget hard-stop was hit (FR-COST-02)."""

    status_code = 429
    reason = "budget_exceeded"


class DepthExceeded(BoltrigError):
    """A spawn beyond max recursion depth was attempted (FR-EXE-03)."""

    status_code = 429
    reason = "depth_exceeded"


class ContextRequirementsUnmet(BoltrigError):
    """A spawn's context did not satisfy the loaded skills' requirements."""

    status_code = 400
    reason = "context_requirements_unmet"

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


class CredentialResolution(BoltrigError):
    """A credential reference could not be resolved from the secret store."""

    status_code = 502
    reason = "credential_resolution_failed"


class SensitiveDataMisrouted(BoltrigError):
    """Sensitive-classified data was about to reach a non-local endpoint (SEC-12)."""

    status_code = 403
    reason = "sensitive_data_misrouted"


class NetworkPolicyViolation(BoltrigError):
    """An egress (web.fetch) target was refused by network policy or SSRF guard.

    Either the NetworkConfig (air-gap / allow / block lists) denied the domain, or
    the target resolved to a private / link-local / metadata address (SEC-52)."""

    status_code = 403
    reason = "network_policy_violation"


# --- Control-flow signals (carry a payload; not failures) ---------------------
class PendingHuman(BoltrigError):
    """Execution paused for a human decision (HITL gate, US-HIL-01).

    Surfaces as ``202 pending_human`` with the created request id.
    """

    status_code = 202
    reason = "pending_human"

    def __init__(self, hitl_request_id: HITLId) -> None:  # noqa: F821 (alias)
        super().__init__(f"pending human: {hitl_request_id}")
        self.hitl_request_id = hitl_request_id


class DegradedMode(BoltrigError):
    """The verb backend was unavailable; a degraded result was produced (P9, K-6 fallback).

    Surfaces as ``503 degraded`` with the degraded output.
    """

    status_code = 503
    reason = "degraded"

    def __init__(self, output: dict[str, Any], deferred: bool = True) -> None:
        super().__init__("degraded result")
        self.output = output
        self.deferred = deferred
