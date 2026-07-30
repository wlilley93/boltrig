"""The "fat library" record types (S6.2): adapters, skills, agent capabilities,
workflow definitions, model endpoints, budgets.

These are *data*. Adding one never changes kernel or agent-runtime code (P1, P7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import (
    AdapterId,
    CapabilityName,
    SkillId,
    TenantId,
    WorkflowId,
    WorkspaceId,
)

# One vocabulary from authoring through selection and fallback pricing.  Unknown
# tiers must not quietly sort after "expensive" while billing as "standard".
COST_TIERS: tuple[str, ...] = ("cheap", "standard", "expensive")


def validate_cost_tier(value: str) -> str:
    if value not in COST_TIERS:
        raise ValueError(f"cost_tier must be one of {', '.join(COST_TIERS)}; got {value!r}")
    return value


class AdapterHealth(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class AdapterRecord:
    id: AdapterId
    tenant_id: TenantId
    version: str
    runtime: str  # 'http' | 'sql' | 'mq' | 'file' | 'script'
    source: str  # 'generated' | 'builtin' | 'manual'
    module_ref: str  # path/reference to the loadable module
    health: AdapterHealth = AdapterHealth.UNKNOWN
    spec_ref: str | None = None  # source OpenAPI/WSDL/schema used to generate
    created_by: str | None = None
    # Generated adapters must pass a human review gate before activation (SEC-22).
    activated: bool = False


@dataclass
class Skill:
    id: SkillId  # e.g. "analysis/ticket-decomposition"
    tenant_id: TenantId
    version: str  # semver
    prompt_fragment: str
    tool_grants: list[str] = field(default_factory=list)  # ["jira.read", "jira.write"]
    context_requirements: dict[str, Any] = field(default_factory=dict)  # JSON Schema
    extends: SkillId | None = None  # optional parent for inheritance
    locale: str = "en"
    # The shelf label: a short "what this is / when to use it" the skill registry
    # exposes for browsing (progressive disclosure) WITHOUT the prompt_fragment
    # body. Empty is allowed; the registry falls back to the id.
    description: str = ""
    # Archival preserves every version and dependency edge while preventing
    # selection until an explicit governed restore.
    is_active: bool = True


@dataclass
class AgentCapability:
    """A runtime profile: a way to run an agent, with a cost tier and skill support."""

    name: CapabilityName  # "hermes-worker"
    tenant_id: TenantId
    runtime: str  # 'hermes' | 'claude-api' | 'script' | 'go-binary'
    supported_skills: list[str]  # patterns: ["writing/*","analysis/*"] or ["*"]
    max_depth: int
    is_ephemeral: bool
    cost_tier: str  # cheap | standard | expensive
    model_endpoint: str | None = None
    # Provenance for scoped-declarative reconciliation ([2026] LEXBY LOG-2026-07-17):
    # 'manifest' rows are authored by the fleet manifest and are reconciled
    # declaratively (a name dropped from a redeployed manifest is deactivated);
    # 'control-plane' rows are governed grants (control.capability.upsert) and are
    # only ever added, never touched by a manifest apply. The default is the
    # fail-safe one: an unattributed row is treated as a governed grant.
    source: str = "control-plane"  # manifest | control-plane
    # Soft-active flag: a deactivated capability is never returned by
    # list_capabilities so select_capability can never route to it.
    is_active: bool = True

    def __post_init__(self) -> None:
        validate_cost_tier(self.cost_tier)


class WorkflowSource(str, Enum):
    PRECREATED = "precreated"
    GENERATED = "generated"
    LEARNED = "learned"


class WorkflowLoopBindingSource(str, Enum):
    """The only runtime values a declarative loop may bind into body params."""

    ITEM = "item"
    INDEX = "index"


WORKFLOW_LOOP_BINDING_SOURCES: tuple[str, ...] = tuple(
    source.value for source in WorkflowLoopBindingSource
)
WORKFLOW_LOOP_MAX_ITEMS = 100
WORKFLOW_LOOP_MAX_BINDINGS = 32
WORKFLOW_LOOP_MAX_BOUND_BYTES = 256 * 1024
WORKFLOW_LOOP_BINDING_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$"


@dataclass
class WorkflowDefinition:
    id: WorkflowId
    tenant_id: TenantId
    version: str
    source: WorkflowSource
    definition: dict[str, Any]  # Hatchet workflow spec
    intent_tags: list[str] = field(default_factory=list)  # for task matching
    origin_task: str | None = None  # work item that generated it (if learned)
    # The WORKSPACE this workflow is scoped to ([2026] VJS-COUNTY 8, D2). NULL means
    # ORG-WIDE: visible + runnable in every workspace of the org, exactly as today
    # (every existing workflow is NULL, so single-tenant deploys are unchanged). A
    # SET value scopes the workflow to that one workspace: match/get/list return it
    # only for a caller whose active workspace is this one (or org-wide), never for
    # a caller in a DIFFERENT workspace. Scoping only NARROWS visibility, never
    # authority (COUNTY 5) - execution authority still comes from the caller ceiling
    # at the dispatch chokepoint. RLS stays tenant_id-fenced; this is an application
    # filter on top (RLS on workspace_id would hide the org-wide NULL rows).
    workspace_id: WorkspaceId | None = None


# A PromotionState enum and a WorkflowPromotion record used to sit here: a stored
# reuse-ranking state for a generated/learned workflow. Both are deleted by [2026]
# VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D3. The reader that consumed the
# value was transitively unreachable from every production entry point, so nothing
# a tenant ran ever observed it. If reuse ranking is ever wanted again it is
# DERIVED from the eval cases and their runs, pinned by the definition digest - no
# table, no writer, no trigger (that order, forbidden clause 4).


@dataclass
class ModelEndpoint:
    id: str  # "anthropic-prod", "local-vllm"
    tenant_id: TenantId
    kind: str  # 'anthropic' | 'openai' | 'ollama' | 'vllm'
    model: str  # pinned model/version
    base_url: str | None = None
    # Stored reference for an explicit, future health-based failover decision.
    # The router does not silently traverse it, especially when this endpoint is
    # retired: withdrawal is a hard stop until an explicit restore.
    fallback: str | None = None
    data_class: str = "standard"  # standard | sensitive (sensitive => local only)
    is_active: bool = True


@dataclass
class Budget:
    id: str  # scope key
    tenant_id: TenantId
    scope_type: str  # tenant | department | workflow
    token_limit: int | None = None
    cost_limit_micros: int | None = None
    hard_stop: bool = True
    window: str = "run"  # run | daily | monthly
    # Usage view projected from the exact budget_usage bucket. The legacy
    # budgets.spent_* columns remain zero after migration.
    spent_tokens: int = 0
    spent_micros: int = 0
    # Exact usage-bucket evidence. A run policy read outside an execution has no
    # honest current bucket, so it reports run_context_required rather than
    # presenting a synthetic zero as live usage.
    usage_state: str = "current"  # current | run_context_required
    window_key: str | None = None
    window_started_at: datetime | None = None
    window_ends_at: datetime | None = None
    reset_generation: int = 0


@dataclass(frozen=True)
class BudgetWindowRef:
    """Exact durable usage bucket selected under a locked budget policy."""

    scope_id: str
    window: str
    window_key: str
    started_at: datetime
    ends_at: datetime | None
    reset_generation: int
