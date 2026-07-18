"""Persistence boundary for digest-only, phase-scoped model-proxy grants."""

from __future__ import annotations

from typing import Protocol

from boltrig.fleet.domain.model_proxy_grant import (
    ModelProxyGrantDraft,
    StoredModelProxyGrant,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
    TrustedModelProxyRequestObservation,
)


class ModelProxyGrantStore(Protocol):
    """Atomic storage that must retain only bearer digests and terminal fences."""

    async def insert_active(self, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
        """Mint authoritative timestamps and insert one exact active generation."""
        ...

    async def find_active_for_trusted_observation(
        self,
        bearer_digest: str,
        observation: TrustedModelProxyRequestObservation,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        """Internal ingress lookup after kernel peer and server-request observation only."""
        ...

    async def find_active_by_id(
        self,
        grant_id: str,
        binding: ModelProxyGrantBinding,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        """Broker-owned metadata check; this does not authenticate a request."""
        ...

    async def get_by_id(
        self, grant_id: str, binding: ModelProxyGrantBinding
    ) -> StoredModelProxyGrant | None: ...

    async def revoke_root(self, scope: ModelProxyRootScope, *, reason: str) -> int: ...

    async def revoke_phase(self, scope: ModelProxyPhaseScope, *, reason: str) -> int: ...

    async def revoke_assignment(self, scope: ModelProxyAssignmentScope, *, reason: str) -> int: ...

    async def revoke_cell(self, scope: ModelProxyCellScope, *, reason: str) -> int: ...


__all__ = ["ModelProxyGrantStore"]
