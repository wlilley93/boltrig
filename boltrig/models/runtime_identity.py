"""Credential-free internal identities minted for governed runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base import utcnow
from .execution_scope import (
    EngineOwner,
    OrganisationUserRef,
    WorkspaceScopeRef,
    _require_aware,
    _require_exact_enum,
    _require_exact_type,
    _require_identifier,
    _require_positive,
)


class RuntimeKind(str, Enum):
    CODEX_APP_SERVER = "codex_app_server"


class RuntimeIdentityStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True)
class RuntimeIdentity:
    """Internal org-user identity; authentication material is resolved elsewhere.

    The persisted record intentionally has no provider subject, credential, key,
    token, email address, home directory, or working-directory location.
    """

    id: str
    principal: OrganisationUserRef
    workspace: WorkspaceScopeRef
    generation: int = 1
    status: RuntimeIdentityStatus = RuntimeIdentityStatus.ACTIVE
    created_at: datetime = field(default_factory=utcnow)
    revoked_at: datetime | None = None
    runtime_kind: RuntimeKind = field(default=RuntimeKind.CODEX_APP_SERVER, init=False)
    engine_owner: EngineOwner = field(default=EngineOwner.BOLTRIG, init=False)

    def __post_init__(self) -> None:
        _require_identifier("runtime identity id", self.id)
        _require_exact_type("principal", self.principal, OrganisationUserRef)
        _require_exact_type("workspace", self.workspace, WorkspaceScopeRef)
        if self.principal.tenant_id != self.workspace.tenant_id:
            raise ValueError("runtime principal and workspace tenants differ")
        _require_positive("generation", self.generation)
        _require_exact_enum("status", self.status, RuntimeIdentityStatus)
        created = _require_aware("created_at", self.created_at)
        if self.revoked_at is not None:
            revoked = _require_aware("revoked_at", self.revoked_at)
            if revoked < created:
                raise ValueError("revoked_at cannot precede created_at")
        if self.status is RuntimeIdentityStatus.ACTIVE and self.revoked_at is not None:
            raise ValueError("active runtime identity cannot have revoked_at")
        if self.status is RuntimeIdentityStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked runtime identity must have revoked_at")
