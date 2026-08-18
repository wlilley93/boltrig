"""Storage for opaque record references (doctrine step 3, SPEC §3).

Two operations, and the interesting one is the write.

``observe_entities`` takes records a read just returned and gives back the ref
each one is known by. It is IDEMPOTENT on the record's identity rather than on
the ref: re-observing a record returns the ref already minted for it, so a ref
the model saw last turn still names the same object this turn. That property is
what makes "update THAT one" work at all, and it lives in the unique index
rather than in a derivation (``boltrig/models/provenance.py`` records why).

``resolve_entity_ref`` is the read, and it is always scoped by tenant AND
workspace. A ref from another tenant, another workspace, or no tenant at all
resolves to None rather than to somebody else's record.
"""

from __future__ import annotations

from collections.abc import Sequence

from boltrig.models.provenance import EntityProvenance

# The identity a ref is idempotent ON. workspace_id is coalesced exactly as the
# unique index coalesces it, so the in-memory store and Postgres agree about
# what "the same record" means - a divergence here would make the memory store
# mint a second ref where Postgres returns the first, and the parity test that
# compares the two stores is what would have to catch it.
def _identity(row: EntityProvenance) -> tuple[str, str, str, str, str]:
    return (
        row.tenant_id,
        row.workspace_id or "",
        row.connection_id,
        row.remote_object_type,
        row.remote_record_id,
    )


def _same_tenant(
    tenant_id: str, candidates: Sequence[EntityProvenance]
) -> Sequence[EntityProvenance]:
    """Refuse a batch that spans tenants.

    ``tenant_id`` leads the signature because ``bind_tenant_on_store_methods``
    reads the first argument to bind the RLS GUC: a bare list is neither a
    string nor tenant-bearing, so the decorator would leave the write UNBOUND
    and the fence would never see it. Since the argument has to be there, it
    may as well be checked - a fan-out assembling rows from several connections
    is precisely where a stray tenant could enter, and one unnoticed row would
    mint a ref in the wrong tenant's namespace.
    """
    wrong = {r.tenant_id for r in candidates} - {tenant_id}
    if wrong:
        raise ValueError(f"provenance batch spans tenants: {sorted(wrong)!r} != {tenant_id!r}")
    return candidates


def _dedupe(candidates: Sequence[EntityProvenance]) -> list[EntityProvenance]:
    """First candidate wins per identity.

    A provider that returns one record twice in a page would otherwise make
    Postgres raise "ON CONFLICT DO UPDATE command cannot affect row a second
    time", turning a merely untidy upstream response into a failed read.
    """
    seen: dict[tuple[str, str, str, str, str], EntityProvenance] = {}
    for row in candidates:
        seen.setdefault(_identity(row), row)
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
        self._by_identity: dict[tuple[str, str, str, str, str], EntityProvenance] = {}

    async def observe_entities(
        self, tenant_id: str, candidates: Sequence[EntityProvenance]
    ) -> list[EntityProvenance]:
        out = []
        for row in _dedupe(_same_tenant(tenant_id, candidates)):
            existing = self._by_identity.get(_identity(row))
            if existing is None:
                self._by_identity[_identity(row)] = row
                out.append(row)
                continue
            # The stored ref wins. Everything else follows the fresh sighting,
            # because a record can be re-read under a newer capability version
            # or through a re-approved binding and the row should say so.
            refreshed = EntityProvenance(
                ref=existing.ref,
                tenant_id=row.tenant_id,
                entity_type=existing.entity_type,
                connection_id=row.connection_id,
                provider=row.provider,
                remote_object_type=row.remote_object_type,
                remote_record_id=row.remote_record_id,
                capability_id=row.capability_id,
                capability_version=row.capability_version,
                binding_id=row.binding_id,
                workspace_id=row.workspace_id,
                created_at=existing.created_at,
                last_seen_at=row.last_seen_at,
            )
            self._by_identity[_identity(row)] = refreshed
            out.append(refreshed)
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
        self, tenant_id: str, candidates: Sequence[EntityProvenance]
    ) -> list[EntityProvenance]:
        rows = _dedupe(_same_tenant(tenant_id, candidates))
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
            by_identity[_identity(row)] = row
        return [by_identity[_identity(r)] for r in rows]

    async def resolve_entity_ref(self, tenant_id, ref, *, workspace_id=None):
        return _provenance(await self._pool.fetchrow(
            """SELECT * FROM entity_provenance
               WHERE tenant_id=$1 AND ref=$2
                 AND coalesce(workspace_id,'') = coalesce($3::text,'')""",
            tenant_id, ref, workspace_id,
        ))
