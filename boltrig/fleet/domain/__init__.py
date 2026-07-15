"""Stable execution-domain types for Boltrig's thin orchestration core."""

from .authority import EffectiveAuthority
from .authority_evaluator import (
    AuthorityEvaluation,
    AuthorityInputs,
    AuthorityLayer,
    AuthorityScope,
    AuthorityScopeMismatch,
    ScopedApproval,
    ScopedGrantSet,
    evaluate_authority,
)
from .execution import (
    ApprovalState,
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseMode,
    PhaseRef,
    PhaseStatus,
    ProfileRef,
    RecordedRuntimeEvent,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SandboxPolicy,
    SkillVersionRef,
)
from .json_types import CanonicalJSON, JSONMapping, JSONValue

__all__ = [
    "ApprovalState",
    "AuthorityEvaluation",
    "AuthorityInputs",
    "AuthorityLayer",
    "AuthorityScope",
    "AuthorityScopeMismatch",
    "CanonicalJSON",
    "EffectiveAuthority",
    "JSONMapping",
    "JSONValue",
    "OrganisationUserRef",
    "PhaseAssignmentRef",
    "PhaseMode",
    "PhaseRef",
    "PhaseStatus",
    "ProfileRef",
    "RecordedRuntimeEvent",
    "RuntimeEvent",
    "RuntimeEventKind",
    "RuntimeThreadRef",
    "RuntimeTurnRef",
    "SandboxPolicy",
    "ScopedApproval",
    "ScopedGrantSet",
    "SkillVersionRef",
    "evaluate_authority",
]
