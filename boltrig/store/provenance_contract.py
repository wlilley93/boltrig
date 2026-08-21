"""Store protocol fragment for opaque record references (doctrine step 3).

``tenant_id`` leads both methods rather than riding inside the payload, because
``bind_tenant_on_store_methods`` binds the RLS GUC from the FIRST argument. A
method whose first argument is a list binds nothing, and an unbound write under
RLS is the failure mode ``boltrig/store/tenant_scope.py`` was written for.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from boltrig.models.provenance import EntityObservation, EntityProvenance


class ProvenanceStoreContract(Protocol):
    # Idempotent on the RECORD's identity, not on the ref: re-observing a record
    # returns the ref already minted for it, which is what lets a model act on a
    # ref it was handed in an earlier turn. THE STORE MINTS: an observation has
    # no ref, so a caller cannot hold one the store discarded on conflict.
    async def observe_entities(
        self, tenant_id: str, observations: Sequence[EntityObservation]
    ) -> list[EntityProvenance]: ...

    # Scoped by tenant AND workspace. A ref from elsewhere resolves to None
    # rather than to someone else's record.
    async def resolve_entity_ref(
        self, tenant_id: str, ref: str, *, workspace_id: str | None = None
    ) -> EntityProvenance | None: ...
