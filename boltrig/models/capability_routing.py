"""Canonical capability routing records (docs/SPEC-capability-doctrine.md §1, §8).

The doctrine separates four concepts that ``verb_bindings`` conflates into one
row:

  A. **Connection** - an authenticated instance that can perform work
     (:class:`ProviderConnection`). ``integration_connections`` stays the
     catalogue-facing presentation row it already is; the ROUTING identity is
     here, which is why the one-active-connection-per-adapter index on that
     table does not bind the three-CRM case (SPEC §11.2, §11.3).
  B. **Source operation** - what a provider actually exposes
     (:class:`SourceOperation`). Provider-prefixed, never shown to the model.
  C. **Canonical capability** - the stable model-facing contract, addressed as
     ``crm.contact.search@1``. WP2 carries its identity on the binding; the
     versioned contract record itself is doctrine step 3.
  D. **Binding** (:class:`CapabilityBinding`) and **route**
     (:class:`RoutingPolicy`) - "this source operation, through this
     connection, implements this capability", and "under these circumstances
     select this binding".

``binding_id`` is its own identity: a capability may have many bindings, and a
second binding never replaces a first. That is the whole point of the shard -
the single-binding contract lives on ``verb_bindings`` (one adapter executes
one source operation, which remains correct), NOT on the capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, utcnow

CONNECTION_SOURCE_TYPES = ("nango", "mcp", "openapi", "sdk_plugin", "native")
CONNECTION_HEALTH = ("unknown", "pending", "ok", "degraded", "down", "revoked")
CONNECTION_STATUS = ("active", "disabled", "revoked")
TRUST_LEVELS = ("untrusted", "reviewed", "trusted", "first_party")
BINDING_STATUS = ("proposed", "approved", "disabled", "retired")
BINDING_ORIGINS = ("declared", "mapping_pack", "structural", "ai_assisted", "manual")
OPERATION_CLASSES = ("read", "create", "update", "delete")
POLICY_SCOPES = ("tenant", "workspace")

# A capability is addressed as ``id@version``. The bare id means "the tenant's
# only live version"; an explicit ``@N`` pins one. Kept here rather than in the
# resolver so the store, the registry and the kernel all spell it once.
CAPABILITY_VERSION_SEPARATOR = "@"


def capability_ref(capability_id: str, version: int) -> str:
    """The addressable name of one capability version."""
    return f"{capability_id}{CAPABILITY_VERSION_SEPARATOR}{int(version)}"


def parse_capability_ref(name: str) -> tuple[str, int | None]:
    """Split ``crm.contact.search@1`` into its id and pinned version.

    An absent or non-numeric suffix yields ``None`` for the version, which the
    resolver reads as "any live version" rather than as an error: a malformed
    pin must not become a silent route to a different capability.
    """
    head, separator, tail = name.rpartition(CAPABILITY_VERSION_SEPARATOR)
    if not separator or not head:
        return name, None
    return (head, int(tail)) if tail.isdigit() else (name, None)


@dataclass
class ProviderConnection:
    """One authenticated instance of a provider (doctrine concept A)."""

    id: str
    tenant_id: TenantId
    label: str
    provider: str
    source_type: str = "native"
    adapter_id: str | None = None
    integration_connection_id: str | None = None
    workspace_id: str | None = None
    account_ref: str | None = None
    credential_ref: str | None = None
    health: str = "unknown"
    status: str = "active"
    trust_level: str = "untrusted"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.source_type not in CONNECTION_SOURCE_TYPES:
            raise ValueError("unsupported connection source type")
        if self.health not in CONNECTION_HEALTH:
            raise ValueError("unsupported connection health")
        if self.status not in CONNECTION_STATUS:
            raise ValueError("unsupported connection status")
        if self.trust_level not in TRUST_LEVELS:
            raise ValueError("unsupported connection trust level")

    @property
    def eligible(self) -> bool:
        """Whether a binding through this connection may be selected at all."""
        return self.status == "active" and self.health not in ("revoked", "down")


@dataclass
class SourceOperation:
    """What a provider exposes, verbatim (doctrine concept B)."""

    id: str
    tenant_id: TenantId
    provider: str
    source_type: str = "native"
    connection_id: str | None = None
    title: str | None = None
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    schema_digest: str = ""
    catalogue_revision: str | None = None
    consequence_hint: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.source_type not in CONNECTION_SOURCE_TYPES:
            raise ValueError("unsupported source operation source type")


@dataclass
class CapabilityBinding:
    """One implementation claim: this source operation, through this
    connection, implements this capability (doctrine concept D, binding half)."""

    binding_id: str
    tenant_id: TenantId
    capability_id: str
    source_operation_id: str
    connection_id: str
    capability_version: int = 1
    status: str = "proposed"
    trust_level: str = "untrusted"
    priority: int = 100
    workspace_predicate: str | None = None
    input_transform_ref: str | None = None
    output_transform_ref: str | None = None
    source_schema_digest: str | None = None
    consequence_override: str | None = None
    health: str = "unknown"
    fallback_policy: str = "none"
    created_from: str = "manual"
    reviewed_by: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.status not in BINDING_STATUS:
            raise ValueError("unsupported binding status")
        if self.trust_level not in TRUST_LEVELS:
            raise ValueError("unsupported binding trust level")
        if self.created_from not in BINDING_ORIGINS:
            raise ValueError("unsupported binding origin")

    @property
    def ref(self) -> str:
        return capability_ref(self.capability_id, self.capability_version)

    def serves(self, workspace_id: str | None) -> bool:
        """Whether this binding is in scope for a workspace.

        ``workspace_predicate`` is None for a tenant-wide binding; a value
        restricts the binding to exactly that workspace. Fail-closed: an
        unbound caller (``workspace_id`` None) never matches a workspace-scoped
        binding.
        """
        return self.workspace_predicate is None or self.workspace_predicate == workspace_id


@dataclass
class RoutingPolicy:
    """Under these circumstances select this binding (doctrine concept D, the
    route half). One row per (capability, scope, operation class)."""

    id: str
    tenant_id: TenantId
    capability_id: str
    binding_id: str
    operation_class: str = "create"
    capability_version: int | None = None
    scope: str = "tenant"
    workspace_id: str | None = None
    precedence: int = 100
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.operation_class not in OPERATION_CLASSES:
            raise ValueError("unsupported routing operation class")
        if self.scope not in POLICY_SCOPES:
            raise ValueError("unsupported routing policy scope")
        if (self.scope == "workspace") != (self.workspace_id is not None):
            raise ValueError("workspace policies require a workspace id")

    def applies(self, version: int, operation_class: str, workspace_id: str | None) -> bool:
        if self.operation_class != operation_class:
            return False
        if self.capability_version is not None and self.capability_version != version:
            return False
        return self.scope == "tenant" or self.workspace_id == workspace_id
