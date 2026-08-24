"""Fleet-manifest typed config dataclasses (moved from config/manifest.py):
frozen data, not behaviour. Re-exported by ``manifest.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from boltrig.identity.rbac import grants_for_scope
from boltrig.config.dev_posture import DevelopmentPosture
from boltrig.config.spawn_rules import SpawnRule
from boltrig.models import GrantSet, ModelEndpoint, RoleMapping

# ChatConfig lives in manifest_chat.py (arc-1); FleetManifest carries a chat
# field and manifest.py re-exports it.
from .manifest_chat import ChatConfig as ChatConfig

# Adapter id -> builtin module providing a ``build() -> Adapter`` factory.
_BUILTIN_MODULES: dict[str, str] = {
    "ms-graph": "boltrig.adapters.builtin.ms_graph",
    "jira": "boltrig.adapters.builtin.jira",
    "crm-sql": "boltrig.adapters.builtin.crm_sql",
    "memory-tickets": "boltrig.adapters.builtin.memory_tickets",
    "runpod": "boltrig.adapters.builtin.runpod",
    "browser-cli": "boltrig.adapters.builtin.browser_cli",
}


# --- typed config dataclasses (frozen; data, not behaviour) -----------------
@dataclass(frozen=True)
class CredentialRef:
    """A reference to secret material - never the material itself (SEC-04)."""

    id: str
    store: str = "env"
    ref: str = ""  # secret-store key; defaults to ``id`` when blank
    kind: str = "api_key"

    def as_ref(self) -> dict[str, str]:
        """The ``{store, ref, kind}`` dict the credential resolver expects."""
        return {"store": self.store, "ref": self.ref or self.id, "kind": self.kind}


@dataclass(frozen=True)
class IdentityConfig:
    """How the tenant authenticates and maps IdP groups to roles (US-IAM-01/02)."""

    provider: str = "oidc"  # 'oidc' | 'cf-access' ('saml' rejected at load, M13)
    issuer: str | None = None
    audience: str | None = None
    jwks_uri: str | None = None
    metadata_url: str | None = None  # SAML IdP metadata (unused until SAML is wired)
    role_mappings: tuple[RoleMapping, ...] = ()


@dataclass(frozen=True)
class ModelsConfig:
    """Inference back ends and routing (P4, SEC sensitive-data residency)."""

    endpoints: tuple[ModelEndpoint, ...] = ()
    default: str | None = None
    sensitive_endpoint: str | None = None  # endpoint id for sensitive data (local)
    # Per-model price table (policy-as-data, FR-COST-04 / audit M14): model name ->
    # micros per token. A model listed here is charged at its real price; a model
    # absent here falls back to its capability's cost-tier default. Replaces static
    # tier micros as the source of truth for cost accounting.
    # Micros per token, FRACTIONAL: every model we route to is cheaper than
    # 1 micro/token ($1.00/M), so an integer rate could not express any of them.
    # A rate is EITHER that single number (one blended rate for every token) OR
    # the published rate card's {input, output} pair - those two prices are not
    # the same number, and an input-heavy agent turn billed at the output rate
    # over-bills substantially. See _parse_price and boltrig/kernel/cost.py.
    prices: Mapping[str, float | Mapping[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class BudgetConfig:
    """A cost / token ceiling for a named agent or ephemeral runtime."""

    token_limit: int | None = None
    cost_limit_micros: int | None = None
    hard_stop: bool = True
    window: str = "run"  # run | daily | monthly

    def __post_init__(self) -> None:
        if self.window not in {"run", "daily", "monthly"}:
            raise ValueError("budget window must be run, daily, or monthly")


@dataclass(frozen=True)
class HierarchyTier:
    """Deprecated Chief/Department manifest record accepted for migration."""

    name: str
    # Compatibility default for old manifests. Codex is the only target agent
    # runtime (decision 0012); an unwired Codex degrades to a deterministic
    # script run rather than crashing.
    runtime: str = "codex"
    model_endpoint: str | None = None
    max_depth: int = 3
    supported_skills: tuple[str, ...] = ("*",)
    cost_tier: str = "standard"
    department: str | None = None
    budget: BudgetConfig | None = None
    # Authored permanent-fleet identity. build_org consumes both fields into the
    # lazy permanent runtime profile; they become model prompt policy only when a
    # call passes the existing runtime admission gates. Deterministic fallback
    # routing/decomposition remains available when that runtime is unavailable.
    purpose: str = ""
    brief: str = ""


@dataclass(frozen=True)
class HierarchyConfig:
    """Deprecated input bridge for pre-flat manifests.

    Runtime composition consumes :func:`resolved_named_agents`; this shape is
    retained so an existing deployment can migrate without a flag day.
    """

    tier1: HierarchyTier | None = None
    tier2: tuple[HierarchyTier, ...] = ()


@dataclass(frozen=True)
class NamedAgentConfig:
    """One durable, addressable tier-1 peer declared by the manifest."""

    name: str
    address: str
    runtime: str = "codex"
    model_endpoint: str | None = None
    max_depth: int = 3
    supported_skills: tuple[str, ...] = ("*",)
    cost_tier: str = "standard"
    scope_id: str | None = None
    budget: BudgetConfig | None = None
    purpose: str = ""
    brief: str = ""


@dataclass(frozen=True)
class NamedAgentsConfig:
    """A flat roster plus the peer that receives unaddressed work."""

    default: str | None = None
    members: tuple[NamedAgentConfig, ...] = ()

    def __post_init__(self) -> None:
        addresses = [member.address for member in self.members]
        names = [member.name for member in self.members]
        if len(addresses) != len(set(addresses)) or len(names) != len(set(names)):
            raise ValueError("named agent names and addresses must be unique")
        if self.members and self.default not in set(addresses):
            raise ValueError("agents.default must name a declared agent address")


@dataclass(frozen=True)
class EphemeralRuntime:
    """A way to run a short-lived child agent (a runtime profile / capability)."""

    name: str
    # Compatibility default for old manifests; v2 should name explicit runtime
    # profiles. Codex is the only target agent runtime (decision 0012); an
    # unwired Codex degrades to a deterministic script run rather than crashing.
    runtime: str = "codex"
    supported_skills: tuple[str, ...] = ("*",)
    max_depth: int = 2
    cost_tier: str = "cheap"
    model_endpoint: str | None = None


@dataclass(frozen=True)
class AdapterConfig:
    """An integration the tenant uses and the credential it resolves (S7)."""

    id: str
    runtime: str = "http"
    credential: CredentialRef | None = None
    version: str = "0.1.0"
    source: str = "builtin"
    module_ref: str = ""


# The floor on the shipped approval window
# ([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D5).
#
# It shipped as 3600. An hour is not a window a human can answer: on Classical
# Visas three control-verb approvals expired unheard on it, and the operator
# experienced that as a four-eyes DEADLOCK and applied to open the host boundary.
# The court found there was no deadlock - the in-band route was open the whole
# time - and that the one-hour window "is the actual proximate cause of what was
# experienced as deadlock". A control that is unanswerable in practice does not
# read as a control; it reads as a bug in the thing it guards, and the cure
# proposed for it was a permanent carve-out.
#
# Both the dataclass default and the parser fallback below must carry this, and
# they must agree: a manifest that omits the key and a manifest that has no hitl
# block at all are the same tenant posture, so both must resolve through
# ``APPROVAL_TIMEOUT_SECONDS_FLOOR`` and cannot resolve differently.
APPROVAL_TIMEOUT_SECONDS_FLOOR = 86400


@dataclass(frozen=True)
class HitlConfig:
    """Human-in-the-loop routing and the verbs that always block (S8, P5)."""

    primary_channel: str = "slack"
    notify_via: tuple[str, ...] = ()
    approval_timeout_seconds: int = APPROVAL_TIMEOUT_SECONDS_FLOOR
    escalation_chain: tuple[str, ...] = ()
    blocking_verbs: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetworkConfig:
    """Egress posture for adapter calls (proxy / CA / air-gap)."""

    air_gapped: bool = False
    https_proxy: str | None = None
    ca_bundle: str | None = None
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()

    def as_egress_config(self) -> dict[str, Any]:
        """The dict shape the shared egress guard consumes (SEC-52): one place
        so every adapter family threads the identical posture."""
        return {
            "air_gapped": self.air_gapped,
            "https_proxy": self.https_proxy,
            "ca_bundle": self.ca_bundle,
            "allowed_domains": self.allowed_domains,
            "blocked_domains": self.blocked_domains,
        }


@dataclass(frozen=True)
class PrivacyConfig:
    """Data-handling posture (PII redaction / residency / retention)."""

    pii_redaction: bool = False
    data_residency: str | None = None
    retention_days: int | None = None
    redact_fields: tuple[str, ...] = ()


# Attachment caps ([2026] VJS-COUNTY 3): conservative, NON-ZERO code defaults for
# inline message attachments. They are the ceiling - a manifest may only TIGHTEN a
# cap (min(default, manifest)), never loosen it (see ``_tighten_cap`` below). Kept
# deliberately small because an attachment is an inline blob on the message row
# (row-growth cost is real; docs/decisions/0006-inline-chat-attachments.md).


@dataclass(frozen=True)
class FleetManifest:
    """The fully-typed fleet manifest (S11.2)."""

    organisation: str
    tenant_id: str
    locale_default: str = "en"
    timezone_default: str = "UTC"
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    named_agents: NamedAgentsConfig = field(default_factory=NamedAgentsConfig)
    hierarchy: HierarchyConfig = field(default_factory=HierarchyConfig)
    ephemeral_runtimes: tuple[EphemeralRuntime, ...] = ()
    spawn_rules: tuple[SpawnRule, ...] = ()
    adapters: tuple[AdapterConfig, ...] = ()
    hitl: HitlConfig = field(default_factory=HitlConfig)
    # The tenant's declared development posture (config/dev_posture.py). Default
    # is NOT declared, so a manifest that says nothing gets full four-eyes.
    development_posture: DevelopmentPosture = field(default_factory=DevelopmentPosture)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    # Raw config sections include Round Three+, memory, and first-party Knowledge.
    extra: dict[str, Any] = field(default_factory=dict)

    def section(self, name: str) -> dict[str, Any]:
        """A raw manifest section by name (empty dict if absent)."""
        value = self.extra.get(name)
        return dict(value) if isinstance(value, dict) else {}

    @property
    def role_mappings(self) -> tuple[RoleMapping, ...]:
        """The IdP-group -> role/scope mappings (for the principal resolver)."""
        return self.identity.role_mappings

    def blocking_verbs(self) -> set[str]:
        """Verbs that always require human approval (P5) - the Kernel's gate.

        Construct the Kernel with ``blocking_verbs=manifest.blocking_verbs()``.
        """
        return set(self.hitl.blocking_verbs)

    def tenant_grants(self) -> GrantSet:
        """The tenant's verb ceiling from its role mappings (US-IAM-04).

        Org-admin (or any ``{all: true}`` scope) yields the tenant-wide ``["*"]``
        grant; otherwise the ceiling is the union of every mapping's verb / noun
        patterns. Denies union (deny-dominant, K-5). Seed the store with
        ``TenantPermissions(tenant_id, manifest.tenant_grants())``.
        """
        allow: set[str] = set()
        deny: set[str] = set()
        for m in self.identity.role_mappings:
            gs = grants_for_scope(m.scope)
            allow.update(gs.allow)
            deny.update(gs.deny)
            if m.role == "org-admin":
                allow.add("*")
        # Internal peer coordination is part of the named-agent substrate. It
        # enters a caller context only after the durable tier-1 sender check;
        # adding it to this independent tenant ceiling does not grant it to a
        # human or ephemeral context.
        allow.update(("agent.send", "chat.present"))
        if "*" in allow:
            return GrantSet.of(["*"], deny=sorted(deny))
        return GrantSet.of(sorted(allow), deny=sorted(deny))
