"""Memory/Postgres parity for opaque record references (doctrine step 3).

The Postgres half carries the risk. Its idempotency is an ``ON CONFLICT``
against an EXPRESSION index (``coalesce(workspace_id,'')``), so the conflict
target has to match the index exactly or the statement errors rather than
upserting; and it maps its RETURNING rows back by identity rather than by
position, because RETURNING has no guaranteed order. Neither property is
observable from the in-memory store, so both are asserted here against a real
database.
"""

from __future__ import annotations

import os

import pytest

from boltrig.models.capability_routing import ProviderConnection
from boltrig.models.provenance import EntityObservation

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "provenance-store-tenant"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    # Scoped to this test's own tenant, NOT `TRUNCATE ... CASCADE`. The obvious
    # truncate reaches much further than it looks: provider_connections is the
    # FK parent of capability_bindings and source_operations, so cascading it
    # empties two tables this file never mentions. It did, and the shared-database
    # run failed in tests/integration/test_backup_restore.py, which passes alone.
    await store._pool.execute("DELETE FROM entity_provenance WHERE tenant_id=$1", T)
    await store._pool.execute("DELETE FROM provider_connections WHERE tenant_id=$1", T)
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def provenance_store(request):
    store = await _make_store(request.param)
    # entity_provenance carries an FK onto the connection, so the routing
    # identity has to exist before a record can point at it.
    await store.upsert_provider_connection(
        ProviderConnection(
            id="pconn:opbox", tenant_id=T, label="Opbox", provider="opbox", adapter_id="opbox"
        )
    )
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _obs(record_id: str, *, workspace: str | None = None) -> EntityObservation:
    return EntityObservation(
        entity_type="matter",
        connection_id="pconn:opbox",
        provider="opbox",
        remote_object_type="matters",
        remote_record_id=record_id,
        capability_id="matter.get",
        workspace_id=workspace,
    )


async def test_a_record_keeps_the_ref_it_was_first_given(provenance_store):
    first, = await provenance_store.observe_entities(T, [_obs("m-1")])
    again, = await provenance_store.observe_entities(T, [_obs("m-1")])

    assert first.ref == again.ref


async def test_distinct_records_get_distinct_refs(provenance_store):
    rows = await provenance_store.observe_entities(T, [_obs("m-1"), _obs("m-2")])

    assert len({row.ref for row in rows}) == 2


async def test_each_returned_row_is_the_record_it_was_asked_about(provenance_store):
    """RETURNING has no guaranteed order, so the PG store maps back by identity.

    Zipping the returned rows against the input would pair a record with
    another record's ref, and with refs being opaque nobody would notice.
    """
    ids = [f"m-{n}" for n in range(12)]

    rows = await provenance_store.observe_entities(T, [_obs(i) for i in ids])

    assert [row.remote_record_id for row in rows] == ids


async def test_a_tenant_wide_sighting_is_idempotent_too(provenance_store):
    """The NULL workspace case, which is the one the coalesce exists for.

    Postgres treats NULLs as distinct in a unique index, so without the
    coalesce every tenant-wide sighting would mint a fresh ref.
    """
    first, = await provenance_store.observe_entities(T, [_obs("m-9", workspace=None)])
    again, = await provenance_store.observe_entities(T, [_obs("m-9", workspace=None)])

    assert first.ref == again.ref
    assert first.workspace_id is None


async def test_the_same_record_in_two_workspaces_is_two_refs(provenance_store):
    a, = await provenance_store.observe_entities(T, [_obs("m-3", workspace="ws-a")])
    b, = await provenance_store.observe_entities(T, [_obs("m-3", workspace="ws-b")])

    assert a.ref != b.ref


async def test_a_duplicate_inside_one_batch_does_not_fail_the_write(provenance_store):
    """A provider returning one record twice in a page is untidy, not fatal.

    Postgres would otherwise raise "ON CONFLICT DO UPDATE command cannot affect
    row a second time" and lose the whole read.
    """
    rows = await provenance_store.observe_entities(T, [_obs("m-4"), _obs("m-4")])

    assert len(rows) == 1


async def test_a_ref_resolves_only_inside_its_own_tenant_and_workspace(provenance_store):
    row, = await provenance_store.observe_entities(T, [_obs("m-5", workspace="ws-a")])

    assert (await provenance_store.resolve_entity_ref(T, row.ref, workspace_id="ws-a")) is not None
    assert (await provenance_store.resolve_entity_ref(T, row.ref, workspace_id="ws-b")) is None
    assert (await provenance_store.resolve_entity_ref("other", row.ref, workspace_id="ws-a")) is None


async def test_an_unissued_ref_resolves_to_nothing(provenance_store):
    assert await provenance_store.resolve_entity_ref(T, "brref_matter_neverminted") is None


async def test_a_re_sighting_refreshes_the_binding_but_not_the_name(provenance_store):
    first, = await provenance_store.observe_entities(T, [_obs("m-6")])
    moved = EntityObservation(
        entity_type="matter",
        connection_id="pconn:opbox",
        provider="opbox",
        remote_object_type="matters",
        remote_record_id="m-6",
        capability_id="matter.get",
        capability_version=2,
    )

    again, = await provenance_store.observe_entities(T, [moved])

    assert again.ref == first.ref
    assert again.capability_version == 2
