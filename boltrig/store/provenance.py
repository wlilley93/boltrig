"""Storage for opaque record references (doctrine step 3, SPEC §3).

Two operations, and the interesting one is the write.

``observe_entities`` takes records a read just returned and gives back the ref
each one is known by. It is IDEMPOTENT on the record's identity rather than on
the ref: re-observing a record returns the ref already minted for it, so a ref
the model saw last turn still names the same object this turn. That property is
what makes "update THAT one" work at all, and it lives in the unique index
rather than in a derivation (``boltrig/models/provenance.py`` records why).

THE STORE MINTS, NOT THE CALLER. Callers pass :class:`EntityObservation`, which
has no ref, and get back :class:`EntityProvenance`, which does. A caller that
minted its own would hold a ref the store may have discarded on conflict, and
using it would name a record that does not exist.

``resolve_entity_ref`` is the read, and it is always scoped by tenant AND
workspace. A ref from another tenant, another workspace, or no tenant at all
resolves to None rather than to somebody else's record.
"""

from __future__ import annotations

from collections.abc import Sequence

from boltrig.models.provenance import EntityObservation, EntityProvenance

# The identity a ref is idempotent ON, spelled once for both stores. It takes
# the tenant separately because an observation does not carry one - the tenant
# is the call's, not the record's. workspace_id is coalesced exactly as the
# unique index coalesces it, so the in-memory store and Postgres agree about
# what "the same record" means; a divergence here would make one mint a second
# ref where the other returns the first.
_Identity = tuple[str, str, str, str, str]


def _identity(tenant_id: str, row) -> _Identity:
    return (
        tenant_id,
        row.workspace_id or "",
        row.connection_id,
        row.remote_object_type,
        row.remote_record_id,
    )


def _dedupe(
    tenant_id: str, observations: Sequence[EntityObservation]
) -> list[EntityObservation]:
    """First observation wins per identity.

    A provider returning one record twice in a page would otherwise make
    Postgres raise "ON CONFLICT DO UPDATE command cannot affect row a second
    time", turning a merely untidy upstream response into a failed read.
    """
    seen: dict[_Identity, EntityObservation] = {}
    for row in observations:
        seen.setdefault(_identity(tenant_id, row), row)
    return list(seen.values())


def _provenance(r) -> EntityProvenance | None:
    if r is None:
        return None
    return EntityProvenance(
        ref=r["ref"],
        tenant_id=r["tenant_id"],
        entity_type=r["entity_type"],
        connection_id=r["connection_id"],
        provider=r["provider"],
        remote_object_type=r["remote_object_type"],
        remote_record_id=r["remote_record_id"],
        capability_id=r["capability_id"],
        capability_version=r["capability_version"],
        binding_id=r["binding_id"],
        workspace_id=r["workspace_id"],
        created_at=r["created_at"],
        last_seen_at=r["last_seen_at"],
    )


class ProvenanceStoreMem:
    def _init_provenance_state(self) -> None:
        self._by_identity: dict[_Identity, EntityProvenance] = {}

    async def observe_entities(
        self, tenant_id: str, observations: Sequence[EntityObservation]
    ) -> list[EntityProvenance]:
        out = []
        for row in _dedupe(tenant_id, observations):
            key = _identity(tenant_id, row)
            existing = self._by_identity.get(key)
            issued = row.issue(tenant_id)
            if existing is not None:
                # The stored ref and entity type win; everything else follows
                # the fresh sighting, because a record can be re-read under a
                # newer capability version or a re-approved binding.
                issued = EntityProvenance(
                    ref=existing.ref,
                    tenant_id=tenant_id,
                    entity_type=existing.entity_type,
                    connection_id=issued.connection_id,
                    provider=issued.provider,
                    remote_object_type=issued.remote_object_type,
                    remote_record_id=issued.remote_record_id,
                    capability_id=issued.capability_id,
                    capability_version=issued.capability_version,
                    binding_id=issued.binding_id,
                    workspace_id=issued.workspace_id,
                    created_at=existing.created_at,
                )
            self._by_identity[key] = issued
            out.append(issued)
        return out

    async def resolve_entity_ref(self, tenant_id, ref, *, workspace_id=None):
        for row in self._by_identity.values():
            if (
                row.tenant_id == tenant_id
                and row.ref == ref
                and (row.workspace_id or "") == (workspace_id or "")
            ):
                return row
        return None


class ProvenanceStorePG:
    async def observe_entities(
        self, tenant_id: str, observations: Sequence[EntityObservation]
    ) -> list[EntityProvenance]:
        rows = [row.issue(tenant_id) for row in _dedupe(tenant_id, observations)]
        if not rows:
            return []
        returned = await self._pool.fetch(
            """INSERT INTO entity_provenance (
                 ref, tenant_id, entity_type, connection_id, provider,
                 remote_object_type, remote_record_id, capability_id,
                 capability_version, binding_id, workspace_id
               )
               SELECT * FROM unnest(
                 $1::text[], $2::text[], $3::text[], $4::text[], $5::text[],
                 $6::text[], $7::text[], $8::text[], $9::int[], $10::text[],
                 $11::text[]
               )
               ON CONFLICT (
                 tenant_id, coalesce(workspace_id, ''), connection_id,
                 remote_object_type, remote_record_id
               ) DO UPDATE SET
                 -- ref and entity_type are NOT updated: the ref already handed
                 -- to a model is the one that must keep resolving, and the type
                 -- is embedded in it, so moving either would strand the name.
                 provider=EXCLUDED.provider,
                 capability_id=EXCLUDED.capability_id,
                 capability_version=EXCLUDED.capability_version,
                 binding_id=EXCLUDED.binding_id,
                 last_seen_at=now()
               RETURNING *""",
            [r.ref for r in rows],
            [r.tenant_id for r in rows],
            [r.entity_type for r in rows],
            [r.connection_id for r in rows],
            [r.provider for r in rows],
            [r.remote_object_type for r in rows],
            [r.remote_record_id for r in rows],
            [r.capability_id for r in rows],
            [r.capability_version for r in rows],
            [r.binding_id for r in rows],
            [r.workspace_id for r in rows],
        )
        # RETURNING has no guaranteed order, so match back on the identity
        # rather than by position. Zipping these lists would silently pair a
        # record with another record's ref.
        by_identity = {}
        for raw in returned:
            row = _provenance(raw)
            by_identity[_identity(tenant_id, row)] = row
        return [by_identity[_identity(tenant_id, r)] for r in rows]

    async def resolve_entity_ref(self, tenant_id, ref, *, workspace_id=None):
        return _provenance(await self._pool.fetchrow(
            """SELECT * FROM entity_provenance
               WHERE tenant_id=$1 AND ref=$2
                 AND coalesce(workspace_id,'') = coalesce($3::text,'')""",
            tenant_id, ref, workspace_id,
        ))
