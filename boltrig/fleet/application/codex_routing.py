"""Select and pin a root-run engine from immutable server-owned policy."""

from __future__ import annotations

import hashlib
import hmac

from boltrig.fleet.domain.codex_rollout import (
    CANARY_BUCKETS,
    CanaryScope,
    CodexCompatibility,
    CodexRolloutMode,
    CodexRolloutPolicy,
    EngineRoute,
    ExecutionResultSource,
    RootEngineDecision,
    RootRoutingFacts,
    RootWorkload,
    RoutingReason,
)


class CodexRoutingRejected(PermissionError):
    """A root could not be routed without weakening the rollout contract."""


class StaleRolloutGeneration(CodexRoutingRejected):
    """A new-root request did not target the active policy generation."""


class RootDecisionConflict(CodexRoutingRejected):
    """An operation attempted to replace or reuse another root's decision."""


class UnsafeShadowRouting(CodexRoutingRejected):
    """Shadow execution was requested for a root that may write."""


def _decision(
    policy: CodexRolloutPolicy,
    facts: RootRoutingFacts,
    *,
    route: EngineRoute,
    result_source: ExecutionResultSource,
    reason: RoutingReason,
    canary_bucket: int | None = None,
) -> RootEngineDecision:
    return RootEngineDecision(
        scope=facts.scope,
        workload=facts.workload,
        compatibility=facts.compatibility,
        policy_generation=policy.generation,
        policy_digest=policy.digest,
        route=route,
        execution_result_source=result_source,
        reason_code=reason,
        canary_bucket=canary_bucket,
    )


def _legacy(
    policy: CodexRolloutPolicy,
    facts: RootRoutingFacts,
    reason: RoutingReason,
    *,
    canary_bucket: int | None = None,
) -> RootEngineDecision:
    return _decision(
        policy,
        facts,
        route=EngineRoute.LEGACY,
        result_source=ExecutionResultSource.LEGACY,
        reason=reason,
        canary_bucket=canary_bucket,
    )


def _is_allowlisted(policy: CodexRolloutPolicy, facts: RootRoutingFacts) -> bool:
    target = CanaryScope(facts.scope.tenant_id, facts.scope.workspace_id)
    return target in policy.canary_allowlist


def _canary_bucket(policy: CodexRolloutPolicy, facts: RootRoutingFacts) -> int:
    key = policy.canary_hash_key
    if type(key) is not bytes:
        raise CodexRoutingRejected("canary policy has no immutable server hash key")
    digest = hmac.new(key, facts.scope.canonical_bytes(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], byteorder="big") % CANARY_BUCKETS


def _route_canary(
    policy: CodexRolloutPolicy, facts: RootRoutingFacts
) -> RootEngineDecision:
    if not _is_allowlisted(policy, facts):
        return _legacy(policy, facts, RoutingReason.CANARY_SCOPE_NOT_ALLOWLISTED)
    bucket = _canary_bucket(policy, facts)
    if bucket >= policy.canary_percentage * (CANARY_BUCKETS // 100):
        return _legacy(
            policy,
            facts,
            RoutingReason.CANARY_NOT_SELECTED,
            canary_bucket=bucket,
        )
    return _decision(
        policy,
        facts,
        route=EngineRoute.CODEX_APP_SERVER,
        result_source=ExecutionResultSource.CODEX_APP_SERVER,
        reason=RoutingReason.CANARY_SELECTED,
        canary_bucket=bucket,
    )


def _route_new_root(
    policy: CodexRolloutPolicy, facts: RootRoutingFacts
) -> RootEngineDecision:
    if policy.emergency_rollback:
        return _legacy(policy, facts, RoutingReason.EMERGENCY_ROLLBACK)
    if policy.mode is CodexRolloutMode.OFF:
        return _legacy(policy, facts, RoutingReason.ROLLOUT_OFF)
    if facts.compatibility is CodexCompatibility.INELIGIBLE:
        return _legacy(policy, facts, RoutingReason.ROOT_INELIGIBLE)
    if policy.mode is CodexRolloutMode.SHADOW:
        if facts.workload is not RootWorkload.BOUNDED_READ_ONLY:
            raise UnsafeShadowRouting("Codex shadowing is limited to bounded read-only roots")
        return _decision(
            policy,
            facts,
            route=EngineRoute.LEGACY_PRIMARY_CODEX_SHADOW,
            result_source=ExecutionResultSource.LEGACY,
            reason=RoutingReason.READ_ONLY_SHADOW,
        )
    if policy.mode is CodexRolloutMode.CANARY:
        return _route_canary(policy, facts)
    if policy.mode is CodexRolloutMode.DEFAULT:
        return _decision(
            policy,
            facts,
            route=EngineRoute.CODEX_APP_SERVER,
            result_source=ExecutionResultSource.CODEX_APP_SERVER,
            reason=RoutingReason.DEFAULT_SELECTED,
        )
    raise CodexRoutingRejected("unknown rollout mode")


class CodexRolloutRouter:
    """Resolve a new root once, or return its exact persisted decision forever."""

    def __init__(self, policy: CodexRolloutPolicy) -> None:
        if type(policy) is not CodexRolloutPolicy:
            raise TypeError("policy must be an exact CodexRolloutPolicy")
        self._policy = policy

    def decide(
        self,
        facts: RootRoutingFacts,
        *,
        persisted_decision: RootEngineDecision | None = None,
    ) -> RootEngineDecision:
        if type(facts) is not RootRoutingFacts:
            raise TypeError("facts must be exact RootRoutingFacts")
        if persisted_decision is not None:
            return self._existing(facts, persisted_decision)
        if facts.expected_policy_generation != self._policy.generation:
            raise StaleRolloutGeneration(
                "new root expected a stale rollout policy generation"
            )
        return _route_new_root(self._policy, facts)

    @staticmethod
    def _existing(
        facts: RootRoutingFacts, persisted: RootEngineDecision
    ) -> RootEngineDecision:
        if type(persisted) is not RootEngineDecision:
            raise TypeError("persisted_decision must be an exact RootEngineDecision")
        if persisted.scope != facts.scope:
            raise RootDecisionConflict("persisted routing decision belongs to another root")
        if (
            persisted.workload is not facts.workload
            or persisted.compatibility is not facts.compatibility
        ):
            raise RootDecisionConflict("immutable root routing facts changed in flight")
        if persisted.policy_generation != facts.expected_policy_generation:
            raise RootDecisionConflict("in-flight root cannot switch policy generation")
        return persisted


__all__ = [
    "CodexRolloutRouter",
    "CodexRoutingRejected",
    "RootDecisionConflict",
    "StaleRolloutGeneration",
    "UnsafeShadowRouting",
]
