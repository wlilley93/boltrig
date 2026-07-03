"""Org -> workspace tenancy models ([2026] VJS-COUNTY 8).

The ORGANISATION is the tenant boundary (D1): an organisation row's ``id`` IS the
``tenant_id`` - exactly one organisation per tenant_id - so tenant isolation
(SEC-08) is unchanged and RLS stays keyed on ``tenant_id``. A WORKSPACE belongs to
exactly one org (D2) and is tenant-scoped. Membership (D3) is modelled separately:
``OrgMember`` confers an org-level role from the existing platform role vocabulary
(``rbac.ROLE_PRECEDENCE``); ``WorkspaceMember`` confers a per-workspace role from a
small fixed set (``WORKSPACE_ROLES``) plus optional fine-grained permissions.

This phase is ADDITIVE: it adds the entities and membership ON TOP of the existing
``tenant_id`` isolation key without rewiring any existing resource read. Later
phases thread a workspace scope through the InvocationContext, tenant switching,
per-org AI keys, and workflow scoping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, WorkspaceId, utcnow

# The allowed per-workspace roles (D3). ``owner`` administers the workspace;
# ``admin`` configures it; ``member`` operates in it; ``viewer`` reads only; and
# ``agent`` is a non-human runtime seat. These are the workspace-local roles; the
# org-level role on ``OrgMember`` comes from the platform vocabulary instead.
WORKSPACE_ROLES: frozenset[str] = frozenset(
    {"owner", "admin", "member", "viewer", "agent"}
)


@dataclass
class Organisation:
    """An organisation - the tenant boundary (D1).

    ``id`` IS the ``tenant_id``: there is exactly one organisation per tenant_id,
    so RLS stays keyed on tenant_id. ``allow_own_ai_keys`` and
    ``require_two_factor`` are org-wide policy flags read by later phases; both
    default to the fail-closed / opt-in setting.
    """

    id: TenantId  # == tenant_id (one org per tenant_id)
    name: str
    slug: str  # unique, url-safe handle
    settings: dict[str, Any] = field(default_factory=dict)
    allow_own_ai_keys: bool = False
    require_two_factor: bool = False
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def tenant_id(self) -> TenantId:
        """The org id IS the tenant boundary (D1); exposed for symmetry with the
        other tenant-scoped models, which all carry a ``tenant_id`` attribute."""
        return self.id


@dataclass
class Workspace:
    """A workspace belonging to an org (D2).

    Tenant-scoped: ``tenant_id`` is the owning organisation's id (== an
    ``Organisation.id``), so a workspace always belongs to an org. Schema-only this
    phase: existing resource tables do NOT yet carry a ``workspace_id`` (that is a
    later phase).
    """

    id: WorkspaceId
    tenant_id: TenantId  # the owning organisation (== Organisation.id)
    name: str
    slug: str  # unique, url-safe handle
    settings: dict[str, Any] = field(default_factory=dict)
    status: str = "active"  # active | archived
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class OrgMember:
    """An organisation membership (D3).

    Primary key is ``(tenant_id, user_id)`` - one membership row per user per org.
    ``role`` is drawn from the existing platform role vocabulary
    (``rbac.ROLE_PRECEDENCE``); it confers no authority by itself here, it only
    records the org-level role. Tenant-scoped (RLS).
    """

    user_id: UserId
    tenant_id: TenantId
    role: str = "member"
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class WorkspaceMember:
    """A per-workspace membership (D3).

    Primary key is ``(workspace_id, user_id)``, tenant-scoped by ``tenant_id`` (the
    owning org). ``role`` is one of ``WORKSPACE_ROLES``; ``permissions`` carries
    optional fine-grained overrides that never exceed the role's ceiling. Tenant-
    scoped (RLS).
    """

    user_id: UserId
    workspace_id: WorkspaceId
    tenant_id: TenantId
    role: str = "member"
    permissions: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
