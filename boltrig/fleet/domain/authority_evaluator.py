"""Pure, scope-bound evaluation of the five effective-authority ceilings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from boltrig.models import EMPTY_GRANTS, GrantSet, TenantId, VerbId, WorkspaceId
from boltrig.models.grants import is_safe_identifier, normalize_identifier

from .authority import EffectiveAuthority
from .execution import ApprovalState, PhaseAssignmentRef


def _identifier(label: str, value: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty, trimmed identifier")
    return value


def _grant_pattern(value: str) -> str:
    canonical = normalize_identifier(_identifier("grant pattern", value))
    if canonical != value or not is_safe_identifier(canonical):
        raise ValueError("grant pattern must be a safe canonical identifier")
    if "*" in canonical and canonical != "*":
        if canonical.count("*") != 1 or not canonical.endswith(".*"):
            raise ValueError("grant wildcard must be '*' or one terminal '.*'")
    return canonical


def _canonical_grants(grants: GrantSet) -> GrantSet:
    if not isinstance(grants, GrantSet):
        raise TypeError("authority grants must be a GrantSet")
    return GrantSet(
        allow=tuple(sorted({_grant_pattern(pattern) for pattern in grants.allow})),
        deny=tuple(sorted({_grant_pattern(pattern) for pattern in grants.deny})),
    )


class AuthorityLayer(str, Enum):
    """Fixed evaluation order for the settled authority formula."""

    PARENT_GRANT = "parent_grant"
    PROFILE_CEILING = "profile_ceiling"
    SELECTED_SKILL_REQUIREMENTS = "selected_skill_requirements"
    WORKSPACE_POLICY = "workspace_policy"
    APPROVAL_STATE = "approval_state"


class AuthorityScopeMismatch(ValueError):
    """A policy input belongs to a different organisation or workspace."""

    def __init__(self, layer: AuthorityLayer) -> None:
        self.layer = layer
        super().__init__(f"{layer.value} is bound to another tenant or workspace")


@dataclass(frozen=True, order=True)
class AuthorityScope:
    """Exact organisation/workspace boundary for one policy evaluation."""

    tenant_id: TenantId
    workspace_id: WorkspaceId

    def __post_init__(self) -> None:
        _identifier("tenant_id", self.tenant_id)
        _identifier("workspace_id", self.workspace_id)


@dataclass(frozen=True)
class ScopedGrantSet:
    """An immutable canonical grant ceiling bound to one exact scope."""

    scope: AuthorityScope
    grants: GrantSet

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AuthorityScope):
            raise TypeError("authority scope must be an AuthorityScope")
        object.__setattr__(self, "grants", _canonical_grants(self.grants))


@dataclass(frozen=True)
class ScopedApproval:
    """Current durable approval state plus its exact, scope-bound ceiling."""

    scope: AuthorityScope
    state: ApprovalState
    grants: GrantSet

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AuthorityScope):
            raise TypeError("approval scope must be an AuthorityScope")
        if not isinstance(self.state, ApprovalState):
            raise TypeError("approval state must be an ApprovalState")
        object.__setattr__(self, "grants", _canonical_grants(self.grants))

    @property
    def effective_grants(self) -> GrantSet:
        """Non-current or negative approval states always collapse to deny-all."""

        if self.state in {ApprovalState.NOT_REQUIRED, ApprovalState.APPROVED}:
            return self.grants
        return EMPTY_GRANTS


@dataclass(frozen=True)
class AuthorityInputs:
    """Typed policy inputs; prompts and messages are deliberately absent."""

    assignment: PhaseAssignmentRef
    parent_grant: ScopedGrantSet
    profile_ceiling: ScopedGrantSet
    selected_skill_requirements: ScopedGrantSet
    workspace_policy: ScopedGrantSet
    approval_state: ScopedApproval

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, PhaseAssignmentRef):
            raise TypeError("assignment must be a PhaseAssignmentRef")
        for layer, value in (
            (AuthorityLayer.PARENT_GRANT, self.parent_grant),
            (AuthorityLayer.PROFILE_CEILING, self.profile_ceiling),
            (AuthorityLayer.SELECTED_SKILL_REQUIREMENTS, self.selected_skill_requirements),
            (AuthorityLayer.WORKSPACE_POLICY, self.workspace_policy),
        ):
            if not isinstance(value, ScopedGrantSet):
                raise TypeError(f"{layer.value} must be a ScopedGrantSet")
        if not isinstance(self.approval_state, ScopedApproval):
            raise TypeError("approval_state must be a ScopedApproval")
        expected = AuthorityScope(
            tenant_id=self.assignment.phase.principal.tenant_id,
            workspace_id=self.assignment.phase.workspace_id,
        )
        for layer, scoped in self._scoped_layers():
            if scoped.scope != expected:
                raise AuthorityScopeMismatch(layer)
        if self.approval_state.scope != expected:
            raise AuthorityScopeMismatch(AuthorityLayer.APPROVAL_STATE)

    @property
    def scope(self) -> AuthorityScope:
        return self.parent_grant.scope

    def _scoped_layers(
        self,
    ) -> tuple[
        tuple[AuthorityLayer, ScopedGrantSet],
        tuple[AuthorityLayer, ScopedGrantSet],
        tuple[AuthorityLayer, ScopedGrantSet],
        tuple[AuthorityLayer, ScopedGrantSet],
    ]:
        return (
            (AuthorityLayer.PARENT_GRANT, self.parent_grant),
            (AuthorityLayer.PROFILE_CEILING, self.profile_ceiling),
            (AuthorityLayer.SELECTED_SKILL_REQUIREMENTS, self.selected_skill_requirements),
            (AuthorityLayer.WORKSPACE_POLICY, self.workspace_policy),
        )

    def layers(self) -> tuple[tuple[AuthorityLayer, GrantSet], ...]:
        """Return every ceiling in deterministic formula order."""

        scoped = tuple((layer, value.grants) for layer, value in self._scoped_layers())
        return (*scoped, (AuthorityLayer.APPROVAL_STATE, self.approval_state.effective_grants))

    def effective_authority(self) -> EffectiveAuthority:
        """Build the compatibility value without materialising lossy wildcard intersections."""

        return EffectiveAuthority(
            parent_grant=self.parent_grant.grants,
            profile_ceiling=self.profile_ceiling.grants,
            selected_skill_requirements=self.selected_skill_requirements.grants,
            workspace_policy=self.workspace_policy.grants,
            approval_state=self.approval_state.effective_grants,
        )


@dataclass(frozen=True)
class LayerVerdict:
    layer: AuthorityLayer
    permitted: bool


@dataclass(frozen=True)
class VerbDecision:
    verb_id: VerbId
    permitted: bool
    verdicts: tuple[LayerVerdict, ...]

    @property
    def denied_by(self) -> tuple[AuthorityLayer, ...]:
        return tuple(item.layer for item in self.verdicts if not item.permitted)


@dataclass(frozen=True)
class LayerReduction:
    """Sequential proof that a layer retained or removed candidates but added none."""

    layer: AuthorityLayer
    before: tuple[VerbId, ...]
    retained: tuple[VerbId, ...]
    denied: tuple[VerbId, ...]

    def __post_init__(self) -> None:
        if set(self.retained) | set(self.denied) != set(self.before):
            raise ValueError("authority reduction must partition its input")
        if set(self.retained) & set(self.denied):
            raise ValueError("authority reduction cannot both retain and deny a verb")


@dataclass(frozen=True)
class AuthorityEvaluation:
    """Deterministic, immutable authority result and its audit explanation."""

    scope: AuthorityScope
    authority: EffectiveAuthority
    requested_verbs: tuple[VerbId, ...]
    permitted_verbs: tuple[VerbId, ...]
    reductions: tuple[LayerReduction, ...]
    decisions: tuple[VerbDecision, ...]

    def decision_for(self, verb_id: VerbId) -> VerbDecision:
        for decision in self.decisions:
            if decision.verb_id == verb_id:
                return decision
        raise KeyError("verb was not part of this authority evaluation")


def _requested_verbs(values: Iterable[VerbId]) -> tuple[VerbId, ...]:
    if isinstance(values, str):
        raise TypeError("requested verbs must be an iterable of verb identifiers")
    result: set[VerbId] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError("verb identifier must be a string")
        canonical = normalize_identifier(_identifier("verb_id", value))
        if not is_safe_identifier(canonical) or "*" in canonical:
            raise ValueError("verb_id must be a safe concrete identifier")
        result.add(canonical)
    return tuple(sorted(result))


def evaluate_authority(
    inputs: AuthorityInputs, requested_verbs: Iterable[VerbId]
) -> AuthorityEvaluation:
    """Evaluate every candidate through all five ceilings without external state."""

    if not isinstance(inputs, AuthorityInputs):
        raise TypeError("inputs must be AuthorityInputs")
    requested = _requested_verbs(requested_verbs)
    layers = inputs.layers()
    remaining = requested
    reductions: list[LayerReduction] = []
    for layer, grants in layers:
        retained = tuple(verb for verb in remaining if grants.permits(verb))
        denied = tuple(verb for verb in remaining if not grants.permits(verb))
        reductions.append(LayerReduction(layer, remaining, retained, denied))
        remaining = retained
    decisions = tuple(
        VerbDecision(
            verb_id=verb,
            permitted=all(grants.permits(verb) for _layer, grants in layers),
            verdicts=tuple(
                LayerVerdict(layer=layer, permitted=grants.permits(verb))
                for layer, grants in layers
            ),
        )
        for verb in requested
    )
    return AuthorityEvaluation(
        scope=inputs.scope,
        authority=inputs.effective_authority(),
        requested_verbs=requested,
        permitted_verbs=remaining,
        reductions=tuple(reductions),
        decisions=decisions,
    )
