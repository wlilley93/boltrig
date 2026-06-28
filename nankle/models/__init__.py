"""Nankle domain models.

Domain state is frozen dataclasses (immutable, hashable); API request/response
bodies are Pydantic and live with the FastAPI app.
"""

from __future__ import annotations

from .audit import ActionType, AuditEvent
from .base import (
    AdapterId,
    CapabilityName,
    HITLId,
    NounId,
    RunId,
    SkillId,
    TenantId,
    UserId,
    VerbId,
    WorkflowId,
    WorkItemId,
    utcnow,
)
from .context import InvocationContext
from .conversation import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    MessageRole,
)
from .platform import (
    ConfigRevision,
    EvalCase,
    EvalRun,
    MemoryItem,
    NotificationPref,
    PersonalAgent,
)
from .errors import (
    BindingNotFound,
    BudgetExceeded,
    ContextRequirementsUnmet,
    CredentialResolution,
    DegradedMode,
    DepthExceeded,
    GrantMissing,
    NankleError,
    PendingHuman,
    RateLimited,
    SchemaValidationError,
    SensitiveDataMisrouted,
    TenantIsolation,
)
from .access import (
    PersonalAccessToken,
    UserInvitation,
    UserSession,
    UserSetting,
)
from .grants import EMPTY_GRANTS, GrantSet, TenantPermissions
from .hitl import HITLRequest, HITLResponse, HITLStatus, HITLType, Urgency
from .identity import RoleMapping, User
from .libraries import (
    AdapterHealth,
    AdapterRecord,
    AgentCapability,
    Budget,
    ModelEndpoint,
    Skill,
    WorkflowDefinition,
    WorkflowSource,
)
from .registry import Consequence, Noun, RateLimit, TargetType, Verb, VerbBinding
from .work import WorkItem, WorkStatus

__all__ = [
    "ActionType",
    "AuditEvent",
    "AdapterId",
    "CapabilityName",
    "HITLId",
    "NounId",
    "RunId",
    "SkillId",
    "TenantId",
    "UserId",
    "VerbId",
    "WorkflowId",
    "WorkItemId",
    "utcnow",
    "InvocationContext",
    "Conversation",
    "ConversationMessage",
    "ConversationStatus",
    "MessageRole",
    "ConfigRevision",
    "EvalCase",
    "EvalRun",
    "MemoryItem",
    "NotificationPref",
    "PersonalAgent",
    "NankleError",
    "SchemaValidationError",
    "BindingNotFound",
    "GrantMissing",
    "TenantIsolation",
    "RateLimited",
    "BudgetExceeded",
    "DepthExceeded",
    "ContextRequirementsUnmet",
    "CredentialResolution",
    "SensitiveDataMisrouted",
    "PendingHuman",
    "DegradedMode",
    "EMPTY_GRANTS",
    "GrantSet",
    "TenantPermissions",
    "HITLRequest",
    "HITLResponse",
    "HITLStatus",
    "HITLType",
    "Urgency",
    "RoleMapping",
    "User",
    "PersonalAccessToken",
    "UserInvitation",
    "UserSession",
    "UserSetting",
    "AdapterHealth",
    "AdapterRecord",
    "AgentCapability",
    "Budget",
    "ModelEndpoint",
    "Skill",
    "WorkflowDefinition",
    "WorkflowSource",
    "Consequence",
    "Noun",
    "RateLimit",
    "TargetType",
    "Verb",
    "VerbBinding",
    "WorkItem",
    "WorkStatus",
]
