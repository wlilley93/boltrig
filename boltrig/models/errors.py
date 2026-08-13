"""The kernel error taxonomy.

These map 1:1 to the dispatch contract (S7.1) and are the only ways a verb
invocation can fail. ``PendingHuman`` and ``DegradedMode`` are control-flow
signals, not failures: they carry a result the caller acts on.
"""

from __future__ import annotations

from typing import Any

from .base import HITLId


class BoltrigError(Exception):
    """Base for every kernel-raised error."""

    status_code: int = 500
    reason: str = "internal_error"


class SchemaValidationError(BoltrigError):
    """Verb params (or output) did not match the registered JSON Schema (SEC-21).

    ``errors`` is a list of VALUE-FREE findings, ``{"schema_path": [...], "keyword": "..."}``,
    built by ``kernel.dispatch._validate``. It is deliberately not a list of jsonschema
    messages: those embed the offending instance verbatim, and this object's contents reach an
    append-only, hash-chained store that nothing can edit or delete afterwards.

    See the schema-validation ledger order (county, First Instance, 2026-07-27) and
    ``docs/vjs/2026-VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001-opinion.md``. The rule it
    settles: a field may enter an append-only store only if its value range is closed at build
    time, or its provenance is wholly the schema AND it is name-only.
    """

    status_code = 400
    reason = "schema_invalid"

    def __init__(
        self,
        message: str,
        errors: list[dict[str, Any]] | None = None,
        *,
        schema_digest: str | None = None,
        hints: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []
        self.schema_digest = schema_digest
        # CALLER-ONLY, and never audited. `errors` is value-free because it
        # enters an append-only hash-chained store; `hints` answers the caller's
        # different question - what should I have sent - and is derived from the
        # schema at the moment of failure. That is exactly the disposal the
        # schema-validation ledger order prescribes for everything outside the
        # ledger's own narrow admission rule: "derived at read time from the
        # system of record, pinned by a digest". A live response is not a store.
        self.hints = hints or []

    def audit_detail(self) -> dict[str, Any]:
        """The audit-row fields this failure contributes. Value-free by construction.

        ``truncated`` is present only when findings were dropped, so its absence means the
        list is complete rather than merely short.
        """
        # ``hints`` is deliberately ABSENT here: it carries schema VALUES which
        # VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 forbids in the ledger.
        # ``caller_detail`` returns them instead.
        detail: dict[str, Any] = {"schema_errors": self.errors}
        if self.schema_digest is not None:
            detail["schema_digest"] = self.schema_digest
        if len(self.errors) >= 10:
            detail["truncated"] = True
        return detail

    def caller_detail(self) -> dict[str, Any]:
        """What the CALLER is told: enough to correct the call and retry.

        Returned, never stored. Before this existed the caller received only
        ``{"status":"error","reason":"schema_invalid"}`` - which names the
        failure class and nothing else - so an agent could not tell WHICH field
        was wrong or what shape it wanted. Observed on Classical Visas
        2026-07-29: a model sent ``entities`` as a string where the schema wants
        an array and retried the identical wrong call four times, because the
        answer it got back was the same opaque word each time. A refusal that
        does not say what would have been accepted cannot be acted on.
        """
        detail: dict[str, Any] = {}
        if self.hints:
            detail["schema_hints"] = self.hints
        if self.schema_digest is not None:
            detail["schema_digest"] = self.schema_digest
        return detail


class BindingNotFound(BoltrigError):
    """No verb_binding resolves this verb for this tenant (fail-closed, K-13)."""

    status_code = 404
    reason = "binding_not_found"


class AdapterFailure(BoltrigError):
    """An adapter rejected a call using the shared adapter error taxonomy."""

    def __init__(self, message: str, *, status_code: int, reason: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class GrantMissing(BoltrigError):
    """The caller's grants do not authorise this verb (P8, SEC-07, K-2)."""

    status_code = 403
    reason = "grant_missing"


class HITLStateConflict(BoltrigError):
    """A human-in-the-loop request is no longer answerable in its current state."""

    status_code = 409
    reason = "hitl_state_conflict"


class IdempotencyConflict(BoltrigError):
    """An idempotency key is bound, in flight, or unsafe to replay."""

    status_code = 409
    reason = "idempotency_conflict"


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


class BudgetWindowUnavailable(BudgetExceeded):
    """A run-window budget was reached without an exact run identity."""

    status_code = 409
    reason = "budget_window_unavailable"


class DepthExceeded(BoltrigError):
    """A spawn beyond max recursion depth was attempted (FR-EXE-03)."""

    status_code = 429
    reason = "depth_exceeded"


class SpawnRulePolicyInvalid(BoltrigError):
    """The current spawn-rule snapshot cannot produce one governed route."""

    status_code = 409
    reason = "spawn_rule_policy_invalid"


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


class ModelEndpointUnavailable(BoltrigError):
    """A configured model endpoint is missing or explicitly withdrawn."""

    status_code = 409
    reason = "model_endpoint_unavailable"


class ModelCatalogueUnavailable(BoltrigError):
    """The server-owned Bifrost catalogue could not prove a model route."""

    status_code = 503
    reason = "model_catalogue_unavailable"


class EvalCaseArchived(BoltrigError):
    """An archived evaluation case cannot start a new run."""

    status_code = 409
    reason = "eval_case_archived"


class NetworkPolicyViolation(BoltrigError):
    """An egress (web.fetch) target was refused by network policy or SSRF guard.

    Either the NetworkConfig (air-gap / allow / block lists) denied the domain, or
    the target resolved to a private / link-local / metadata address (SEC-52)."""

    status_code = 403
    reason = "network_policy_violation"


class ApprovalNotHoldable(BoltrigError):
    """A gated verb was dispatched on a lane that could not redeem its approval.

    The subsidiary holding of decision 0018: an approval instrument must never be
    minted on a lane with no redeemer. The live defect it prevents is on the
    record - a human approved ``opbox.add_comment`` inside a chat turn, the
    request sat ANSWERED forever because nothing could claim it, and the comment
    was never posted. A pause that cannot be recorded is refused BEFORE the
    request is created, so the answerable-but-unclaimable state cannot exist.
    """

    status_code = 409
    reason = "approval_not_holdable"

    def __init__(self, message: str, verb: str) -> None:
        super().__init__(message)
        self.verb = verb


# --- Control-flow signals (carry a payload; not failures) ---------------------
class PendingHuman(BoltrigError):
    """Execution paused for a human decision (HITL gate, US-HIL-01).

    Surfaces as ``202 pending_human`` with the created request id.
    """

    status_code = 202
    reason = "pending_human"

    def __init__(self, hitl_request_id: HITLId) -> None:
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
