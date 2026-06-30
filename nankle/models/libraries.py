"""The "fat library" record types (S6.2): adapters, skills, agent capabilities,
workflow definitions, model endpoints, budgets.

These are *data*. Adding one never changes kernel or agent-runtime code (P1, P7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .base import AdapterId, CapabilityName, SkillId, TenantId, WorkflowId


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


class WorkflowSource(str, Enum):
    PRECREATED = "precreated"
    GENERATED = "generated"
    LEARNED = "learned"


@dataclass
class WorkflowDefinition:
    id: WorkflowId
    tenant_id: TenantId
    version: str
    source: WorkflowSource
    definition: dict[str, Any]  # Hatchet workflow spec
    intent_tags: list[str] = field(default_factory=list)  # for task matching
    origin_task: str | None = None  # work item that generated it (if learned)


@dataclass
class ModelEndpoint:
    id: str  # "anthropic-prod", "local-vllm"
    tenant_id: TenantId
    kind: str  # 'anthropic' | 'openai' | 'ollama' | 'vllm'
    model: str  # pinned model/version
    base_url: str | None = None
    fallback: str | None = None  # endpoint id used if this is unavailable
    data_class: str = "standard"  # standard | sensitive (sensitive => local only)


@dataclass
class Budget:
    id: str  # scope key
    tenant_id: TenantId
    scope_type: str  # tenant | department | workflow
    token_limit: int | None = None
    cost_limit_micros: int | None = None
    hard_stop: bool = True
    window: str = "run"  # run | daily | monthly
    # running accumulators (mirrors the spent_* columns in schema.sql)
    spent_tokens: int = 0
    spent_micros: int = 0
