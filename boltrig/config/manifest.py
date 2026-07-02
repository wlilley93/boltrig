"""The fleet manifest: load it, type it, and seed the store from it (S11.2, P7).

Everything that varies between organisations is data, not code (P1/P7). The
fleet manifest is that data: who the org is, how it authenticates, which models
and adapters it uses, the agent hierarchy, the ephemeral runtimes, the HITL
policy, and the network / privacy posture. ``load_manifest`` parses it into
frozen dataclasses (with ``${ENV}`` interpolation); ``apply_manifest`` seeds the
store so the kernel and fleet can run against it. No core code changes to add a
new org, model, capability, or integration.
"""

from __future__ import annotations

import importlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

import yaml

from boltrig.identity.rbac import grants_for_scope
from boltrig.models import (
    AgentCapability,
    Budget,
    GrantSet,
    ModelEndpoint,
    RoleMapping,
    TenantPermissions,
)

# Adapter id -> builtin module providing a ``build() -> Adapter`` factory.
_BUILTIN_MODULES: dict[str, str] = {
    "ms-graph": "boltrig.adapters.builtin.ms_graph",
    "jira": "boltrig.adapters.builtin.jira",
    "crm-sql": "boltrig.adapters.builtin.crm_sql",
    "memory-tickets": "boltrig.adapters.builtin.memory_tickets",
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
    prices: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BudgetConfig:
    """A cost / token ceiling for a hierarchy tier (FR cost-control)."""

    token_limit: int | None = None
    cost_limit_micros: int | None = None
    hard_stop: bool = True
    window: str = "run"  # run | daily | monthly


@dataclass(frozen=True)
class HierarchyTier:
    """A durable agent in the org chart (tier1 chief-of-staff / tier2 head)."""

    name: str
    runtime: str = "hermes"
    model_endpoint: str | None = None
    max_depth: int = 3
    supported_skills: tuple[str, ...] = ("*",)
    cost_tier: str = "standard"
    department: str | None = None
    budget: BudgetConfig | None = None


@dataclass(frozen=True)
class HierarchyConfig:
    """The agent org chart: one tier1 over many tier2 department heads (S6)."""

    tier1: HierarchyTier | None = None
    tier2: tuple[HierarchyTier, ...] = ()


@dataclass(frozen=True)
class EphemeralRuntime:
    """A way to run a short-lived child agent (a runtime profile / capability)."""

    name: str
    runtime: str = "hermes"
    supported_skills: tuple[str, ...] = ("*",)
    max_depth: int = 2
    cost_tier: str = "cheap"
    model_endpoint: str | None = None


@dataclass(frozen=True)
class SpawnRule:
    """A rule for matching a task to a runtime / skill set (S6 spawning)."""

    name: str = ""
    match: dict[str, Any] = field(default_factory=dict)
    capability: str | None = None
    skills: tuple[str, ...] = ()
    max_depth: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterConfig:
    """An integration the tenant uses and the credential it resolves (S7)."""

    id: str
    runtime: str = "http"
    credential: CredentialRef | None = None
    version: str = "0.1.0"
    source: str = "builtin"
    module_ref: str = ""


@dataclass(frozen=True)
class HitlConfig:
    """Human-in-the-loop routing and the verbs that always block (S8, P5)."""

    primary_channel: str = "slack"
    notify_via: tuple[str, ...] = ()
    approval_timeout_seconds: int = 3600
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


@dataclass(frozen=True)
class PrivacyConfig:
    """Data-handling posture (PII redaction / residency / retention)."""

    pii_redaction: bool = False
    data_residency: str | None = None
    retention_days: int | None = None
    redact_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatConfig:
    """Bare chat-turn authority ([2026] VJS-COUNTY 1): which skill set a bare
    chat turn spawns with, per caller role. The turn executor selects
    ``skills_by_role.get(role, default_skills)``; the shipped author-role
    mapping is carried by manifest.example.yaml (policy-as-data, P7), so these
    code defaults stay empty and a manifest-less boot is fail-closed."""

    skills_by_role: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    default_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class FleetManifest:
    """The fully-typed fleet manifest (S11.2)."""

    organisation: str
    tenant_id: str
    locale_default: str = "en"
    timezone_default: str = "UTC"
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    hierarchy: HierarchyConfig = field(default_factory=HierarchyConfig)
    ephemeral_runtimes: tuple[EphemeralRuntime, ...] = ()
    spawn_rules: tuple[SpawnRule, ...] = ()
    adapters: tuple[AdapterConfig, ...] = ()
    hitl: HitlConfig = field(default_factory=HitlConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    # Sections surfaced as raw config rather than typed dataclasses (Round Three+:
    # evaluation/notifications/personal_agents, and Round Five: memory).
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
        if "*" in allow:
            return GrantSet.of(["*"], deny=sorted(deny))
        return GrantSet.of(sorted(allow), deny=sorted(deny))


# --- ${ENV} interpolation ---------------------------------------------------
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate(obj: Any, env: Mapping[str, str]) -> Any:
    """Recursively replace ``${VAR}`` / ``${VAR:-default}`` from ``env``."""
    if isinstance(obj, dict):
        return {k: _interpolate(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate(v, env) for v in obj]
    if isinstance(obj, str):

        def repl(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            return env.get(name, default if default is not None else "")

        return _VAR.sub(repl, obj)
    return obj


# --- parse helpers ----------------------------------------------------------
def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _parse_credential(raw: Any) -> CredentialRef | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return CredentialRef(id=raw, ref=raw)
    cred_id = str(raw["id"])
    return CredentialRef(
        id=cred_id,
        store=str(raw.get("store", "env")),
        ref=str(raw.get("ref") or cred_id),
        kind=str(raw.get("kind", "api_key")),
    )


def _parse_identity(raw: Mapping[str, Any], tenant_id: str) -> IdentityConfig:
    provider = str(raw.get("provider", "oidc"))
    # M13: the manifest can advertise ``provider: saml`` but no SAML assertion
    # validator is wired anywhere (``SamlVerifier.verify`` raises), and resolver
    # selection never reads this field - so a deployment that sets it would
    # silently run env-selected auth while the operator believes SAML is
    # enforced. Fail loudly at load rather than boot a false belief. (SAML stays
    # a seam: supply a concrete assertion validator and select it explicitly.)
    if provider == "saml":
        raise ValueError(
            "identity.provider 'saml' is not implemented; set provider to "
            "'oidc' or 'cf-access' (or supply a SAML assertion validator and "
            "wire it explicitly). See audit finding M13."
        )
    mappings = tuple(
        RoleMapping(
            tenant_id=tenant_id,
            idp_group=str(m["idp_group"]),
            role=str(m["role"]),
            scope=dict(m.get("scope") or {}),
        )
        for m in (raw.get("role_mappings") or [])
    )
    return IdentityConfig(
        provider=provider,
        issuer=raw.get("issuer"),
        audience=raw.get("audience"),
        jwks_uri=raw.get("jwks_uri"),
        metadata_url=raw.get("metadata_url"),
        role_mappings=mappings,
    )


def _parse_models(raw: Mapping[str, Any], tenant_id: str) -> ModelsConfig:
    endpoints = tuple(
        ModelEndpoint(
            id=str(e["id"]),
            tenant_id=tenant_id,
            kind=str(e.get("kind", "anthropic")),
            model=str(e["model"]),
            base_url=e.get("base_url"),
            fallback=e.get("fallback"),
            data_class=str(e.get("data_class", "standard")),
        )
        for e in (raw.get("endpoints") or [])
    )
    # Per-model price table (FR-COST-04): {model_name: micros_per_token}. Values
    # are coerced to int; a malformed entry is dropped rather than failing load, so
    # a bad price never blocks boot (the model just falls back to its tier default).
    prices: dict[str, int] = {}
    for name, rate in (raw.get("prices") or {}).items():
        try:
            prices[str(name)] = int(rate)
        except (TypeError, ValueError):
            continue
    return ModelsConfig(
        endpoints=endpoints,
        default=raw.get("default"),
        sensitive_endpoint=raw.get("sensitive_endpoint"),
        prices=prices,
    )


def _parse_budget(raw: Any) -> BudgetConfig | None:
    if not raw:
        return None
    return BudgetConfig(
        token_limit=raw.get("token_limit"),
        cost_limit_micros=raw.get("cost_limit_micros"),
        hard_stop=bool(raw.get("hard_stop", True)),
        window=str(raw.get("window", "run")),
    )


def _parse_tier(raw: Mapping[str, Any]) -> HierarchyTier:
    skills = raw.get("skills", raw.get("supported_skills", ["*"]))
    return HierarchyTier(
        name=str(raw["name"]),
        runtime=str(raw.get("runtime", "hermes")),
        model_endpoint=raw.get("model_endpoint"),
        max_depth=int(raw.get("max_depth", 3)),
        supported_skills=_as_tuple(skills),
        cost_tier=str(raw.get("cost_tier", "standard")),
        department=raw.get("department"),
        budget=_parse_budget(raw.get("budget")),
    )


def _parse_hierarchy(raw: Mapping[str, Any]) -> HierarchyConfig:
    tier1 = _parse_tier(raw["tier1"]) if raw.get("tier1") else None
    tier2 = tuple(_parse_tier(t) for t in (raw.get("tier2") or []))
    return HierarchyConfig(tier1=tier1, tier2=tier2)


def _parse_ephemeral(raw: Mapping[str, Any]) -> EphemeralRuntime:
    skills = raw.get("supported_skills", raw.get("skills", ["*"]))
    return EphemeralRuntime(
        name=str(raw["name"]),
        runtime=str(raw.get("runtime", "hermes")),
        supported_skills=_as_tuple(skills),
        max_depth=int(raw.get("max_depth", 2)),
        cost_tier=str(raw.get("cost_tier", "cheap")),
        model_endpoint=raw.get("model_endpoint"),
    )


def _parse_spawn_rule(raw: Mapping[str, Any]) -> SpawnRule:
    return SpawnRule(
        name=str(raw.get("name", raw.get("intent", ""))),
        match=dict(raw.get("match") or {}),
        capability=raw.get("capability"),
        skills=_as_tuple(raw.get("skills")),
        max_depth=raw.get("max_depth"),
        raw=dict(raw),
    )


def _parse_adapter(raw: Mapping[str, Any]) -> AdapterConfig:
    adapter_id = str(raw["id"])
    return AdapterConfig(
        id=adapter_id,
        runtime=str(raw.get("runtime", "http")),
        credential=_parse_credential(raw.get("credential")),
        version=str(raw.get("version", "0.1.0")),
        source=str(raw.get("source", "builtin")),
        module_ref=str(raw.get("module_ref") or _BUILTIN_MODULES.get(adapter_id, "")),
    )


def _parse_hitl(raw: Mapping[str, Any]) -> HitlConfig:
    return HitlConfig(
        primary_channel=str(raw.get("primary_channel", "slack")),
        notify_via=_as_tuple(raw.get("notify_via")),
        approval_timeout_seconds=int(raw.get("approval_timeout_seconds", 3600)),
        escalation_chain=_as_tuple(raw.get("escalation_chain")),
        blocking_verbs=_as_tuple(raw.get("blocking_verbs")),
    )


def _parse_network(raw: Mapping[str, Any]) -> NetworkConfig:
    return NetworkConfig(
        air_gapped=bool(raw.get("air_gapped", False)),
        https_proxy=raw.get("https_proxy"),
        ca_bundle=raw.get("ca_bundle"),
        allowed_domains=_as_tuple(raw.get("allowed_domains")),
        blocked_domains=_as_tuple(raw.get("blocked_domains")),
    )


def _parse_privacy(raw: Mapping[str, Any]) -> PrivacyConfig:
    return PrivacyConfig(
        pii_redaction=bool(raw.get("pii_redaction", False)),
        data_residency=raw.get("data_residency"),
        retention_days=raw.get("retention_days"),
        redact_fields=_as_tuple(raw.get("redact_fields")),
    )


def _parse_chat(raw: Mapping[str, Any]) -> ChatConfig:
    skills_by_role = {
        str(role): _as_tuple(skills)
        for role, skills in (raw.get("skills_by_role") or {}).items()
    }
    return ChatConfig(
        skills_by_role=skills_by_role,
        default_skills=_as_tuple(raw.get("default_skills")),
    )


def load_manifest(path: str, *, env: Mapping[str, str] | None = None) -> FleetManifest:
    """Load + type the fleet manifest at ``path`` (S11.2).

    YAML is parsed, ``${ENV}`` references are interpolated from ``env`` (defaults
    to ``os.environ``), and the result is built into frozen dataclasses.
    """
    environ = env if env is not None else os.environ
    with open(path, "r", encoding="utf-8") as fh:
        raw_doc = yaml.safe_load(fh) or {}
    doc: dict[str, Any] = _interpolate(raw_doc, environ)

    tenant_id = str(doc["tenant_id"])
    return FleetManifest(
        organisation=str(doc.get("organisation", tenant_id)),
        tenant_id=tenant_id,
        locale_default=str(doc.get("locale_default", "en")),
        timezone_default=str(doc.get("timezone_default", "UTC")),
        identity=_parse_identity(doc.get("identity") or {}, tenant_id),
        models=_parse_models(doc.get("models") or {}, tenant_id),
        hierarchy=_parse_hierarchy(doc.get("hierarchy") or {}),
        ephemeral_runtimes=tuple(
            _parse_ephemeral(r) for r in (doc.get("ephemeral_runtimes") or [])
        ),
        spawn_rules=tuple(_parse_spawn_rule(r) for r in (doc.get("spawn_rules") or [])),
        adapters=tuple(_parse_adapter(a) for a in (doc.get("adapters") or [])),
        hitl=_parse_hitl(doc.get("hitl") or {}),
        network=_parse_network(doc.get("network") or {}),
        privacy=_parse_privacy(doc.get("privacy") or {}),
        chat=_parse_chat(doc.get("chat") or {}),
        extra={k: doc[k] for k in ("evaluation", "notifications", "personal_agents",
                                   "memory", "runtimes", "mcp", "chat") if k in doc},
    )


# --- applying the manifest to the store -------------------------------------
async def _seed_call(store: Any, method: str, *args: Any) -> None:
    """Call a store seeding helper, awaiting it if it is async (PostgresStore) and
    calling it directly if it is sync (InMemoryStore). Clear error if unsupported."""
    import inspect

    fn = getattr(store, method, None)
    if fn is None:
        raise RuntimeError(
            f"store {type(store).__name__} lacks seed helper {method!r}; "
            "apply_manifest requires a seedable store (e.g. InMemoryStore, PostgresStore)"
        )
    result = fn(*args)
    if inspect.isawaitable(result):
        await result


def _capability_from_tier(tier: HierarchyTier, tenant_id: str) -> AgentCapability:
    return AgentCapability(
        name=tier.name,
        tenant_id=tenant_id,
        runtime=tier.runtime,
        supported_skills=list(tier.supported_skills),
        max_depth=tier.max_depth,
        is_ephemeral=False,
        cost_tier=tier.cost_tier,
        model_endpoint=tier.model_endpoint,
    )


def _capability_from_ephemeral(rt: EphemeralRuntime, tenant_id: str) -> AgentCapability:
    return AgentCapability(
        name=rt.name,
        tenant_id=tenant_id,
        runtime=rt.runtime,
        supported_skills=list(rt.supported_skills),
        max_depth=rt.max_depth,
        is_ephemeral=True,
        cost_tier=rt.cost_tier,
        model_endpoint=rt.model_endpoint,
    )


def _budget_from_tier(
    tier: HierarchyTier, tenant_id: str, *, scope_type: str, scope_id: str
) -> Budget:
    b = tier.budget
    assert b is not None  # guarded by caller
    return Budget(
        id=scope_id,
        tenant_id=tenant_id,
        scope_type=scope_type,
        token_limit=b.token_limit,
        cost_limit_micros=b.cost_limit_micros,
        hard_stop=b.hard_stop,
        window=b.window,
    )


async def apply_manifest(
    kernel: Any, manifest: FleetManifest, *, load_builtin_adapters: bool = True
) -> None:
    """Seed the store from the manifest so the kernel/fleet can run (S11.2, P7).

    Seeds, in order: model endpoints, agent capabilities (ephemeral runtimes and
    hierarchy tiers), tier budgets, tenant permissions, credential references
    (and adapter bindings), then optionally imports + registers the builtin
    adapters named in the manifest. Unknown adapter ids are skipped gracefully.
    """
    tenant = manifest.tenant_id
    store = kernel.store

    # 1. model endpoints (P4) + the per-model price table (FR-COST-04, audit M14).
    #    Prices are policy-as-data on the cost accountant so post-run true-up and
    #    reservations price real spend; absent any prices the tier defaults stand.
    for endpoint in manifest.models.endpoints:
        await store.upsert_model_endpoint(endpoint)
    cost = getattr(kernel, "cost", None)
    if cost is not None and manifest.models.prices:
        cost.set_prices(manifest.models.prices)

    # 2. agent capabilities: ephemeral runtimes + hierarchy tiers
    for rt in manifest.ephemeral_runtimes:
        await store.upsert_capability(_capability_from_ephemeral(rt, tenant))
    tiers: list[HierarchyTier] = []
    if manifest.hierarchy.tier1 is not None:
        tiers.append(manifest.hierarchy.tier1)
    tiers.extend(manifest.hierarchy.tier2)
    for tier in tiers:
        await store.upsert_capability(_capability_from_tier(tier, tenant))

    # 3. budgets from tier budget blocks (FR cost-control)
    if manifest.hierarchy.tier1 is not None and manifest.hierarchy.tier1.budget:
        await _seed_call(
            store,
            "set_budget",
            _budget_from_tier(
                manifest.hierarchy.tier1, tenant, scope_type="tenant", scope_id=tenant
            ),
        )
    for tier in manifest.hierarchy.tier2:
        if tier.budget:
            scope_id = tier.department or tier.name
            await _seed_call(
                store,
                "set_budget",
                _budget_from_tier(
                    tier, tenant, scope_type="department", scope_id=scope_id
                ),
            )

    # 4. tenant permissions (the verb ceiling, US-IAM-04)
    await _seed_call(
        store,
        "set_tenant_permissions",
        TenantPermissions(tenant, manifest.tenant_grants()),
    )

    # 5. credential references + adapter bindings (refs only, SEC-04)
    for adapter in manifest.adapters:
        if adapter.credential is not None:
            cred = adapter.credential
            await _seed_call(store, "set_credential_ref", tenant, cred.id, cred.as_ref())
            kernel.credentials.bind_adapter_credential(tenant, adapter.id, cred.id)

    # 6. adapters: import the module, build(), register (P1). A builtin id maps to
    #    a known module; otherwise the adapter's own `module_ref` ("pkg.mod" or
    #    "pkg.mod:factory") is honoured, so a PROJECT ships its adapter as an
    #    importable module + a manifest entry and extends the kernel from OUTSIDE,
    #    no core edit (the extension contract, Round Fifteen).
    if load_builtin_adapters:
        for adapter in manifest.adapters:
            module_path = _BUILTIN_MODULES.get(adapter.id) or adapter.module_ref
            if not module_path:
                continue  # unknown id and no module_ref -> skip gracefully
            mod_name, _, factory = module_path.partition(":")
            module = importlib.import_module(mod_name)
            build = getattr(module, factory or "build")
            await kernel.register_adapter(tenant, build())
