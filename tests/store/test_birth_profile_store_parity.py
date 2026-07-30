"""Memory/PostgreSQL parity for redacted birth-profile receipts."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import os

import pytest

from boltrig.config.birth_profile import make_birth_profile_receipt
from boltrig.models import (
    BIRTH_PROFILE_MAX_RETURNED_RECEIPTS,
    BIRTH_PROFILE_RECEIPTS_PER_PROCESS,
    utcnow,
)
from boltrig.store.birth_profiles import BirthProfileStorePG

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "birth-profile-store-tenant"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute("TRUNCATE birth_profile_receipts")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN,
                reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity",
            ),
        ),
    ]
)
async def birth_profile_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _receipt(tenant_id: str, process_kind: str, identity: str):
    return make_birth_profile_receipt(
        tenant_id=tenant_id,
        process_kind=process_kind,
        manifest={"generation": 1},
        addons=(),
        codex_config=None,
        sensitive_endpoint_id=None,
        boot_identity_token=identity,
    )


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
@pytest.mark.invariant("SEC-08")
async def test_all_boot_instance_receipts_are_tenant_scoped_on_both_stores(
    birth_profile_store,
) -> None:
    store = birth_profile_store
    first = _receipt(T, "api", "api-a")
    second = replace(
        first,
        instance_identity="bi_" + "b" * 24,
        addon_set_identity="as_" + "c" * 24,
    )
    fleet = _receipt(T, "fleet", "fleet-a")
    other = _receipt("other", "api", "api-other")
    for receipt in (first, second, fleet, other):
        await store.upsert_birth_profile_receipt(receipt)

    rows = await store.list_birth_profile_receipts(T)

    assert {(row.process_kind, row.instance_identity) for row in rows} == {
        ("api", first.instance_identity),
        ("api", second.instance_identity),
        ("fleet", fleet.instance_identity),
    }


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
async def test_repeated_boots_are_pruned_and_queried_with_a_hard_bound(
    birth_profile_store,
) -> None:
    store = birth_profile_store
    base = utcnow()
    attempted_per_process = BIRTH_PROFILE_RECEIPTS_PER_PROCESS + 11
    for process_kind in ("api", "fleet"):
        for index in range(attempted_per_process):
            receipt = _receipt(
                T,
                process_kind,
                f"{process_kind}-boot-{index}",
            )
            observed_at = base + timedelta(seconds=index)
            await store.upsert_birth_profile_receipt(
                replace(
                    receipt,
                    observed_at=observed_at,
                    expires_at=observed_at + timedelta(minutes=5),
                )
            )

    rows = await store.list_birth_profile_receipts(T)

    assert len(rows) == 2 * BIRTH_PROFILE_RECEIPTS_PER_PROCESS
    assert len(rows) <= BIRTH_PROFILE_MAX_RETURNED_RECEIPTS
    for process_kind in ("api", "fleet"):
        retained = [row for row in rows if row.process_kind == process_kind]
        assert len(retained) == BIRTH_PROFILE_RECEIPTS_PER_PROCESS
        assert retained == sorted(
            retained,
            key=lambda row: (row.observed_at, row.instance_identity),
            reverse=True,
        )
        assert min(row.observed_at for row in retained) == (
            base + timedelta(seconds=attempted_per_process - BIRTH_PROFILE_RECEIPTS_PER_PROCESS)
        )

    if hasattr(store, "_birth_profile_receipts"):
        assert len(store._birth_profile_receipts) == len(rows)
    else:
        persisted = await store._pool.fetchval(
            "SELECT count(*) FROM birth_profile_receipts WHERE tenant_id=$1",
            T,
        )
        assert persisted == len(rows)


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeConnection:
    def __init__(self):
        self.executions = []

    def transaction(self):
        return _FakeTransaction()

    async def execute(self, query, *args):
        self.executions.append((query, args))
        return "OK"


class _FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _FakePool:
    def __init__(self):
        self.connection = _FakeConnection()
        self.fetches = []

    def acquire(self):
        return _FakeAcquire(self.connection)

    async def fetch(self, query, *args):
        self.fetches.append((query, args))
        return []


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-30")
async def test_postgres_write_prunes_atomically_and_read_has_a_literal_bound():
    pool = _FakePool()
    store = BirthProfileStorePG()
    store._pool = pool
    receipt = _receipt(T, "api", "bounded-pg")

    await store.upsert_birth_profile_receipt(receipt)
    assert len(pool.connection.executions) == 4
    guc, lock, insert, prune = pool.connection.executions
    assert "set_config('app.tenant_id'" in guc[0]
    assert guc[1] == (T,)
    assert "pg_advisory_xact_lock" in lock[0]
    assert "INSERT INTO birth_profile_receipts" in insert[0]
    assert "OFFSET $3" in prune[0]
    assert prune[1] == (T, "api", BIRTH_PROFILE_RECEIPTS_PER_PROCESS)

    assert await store.list_birth_profile_receipts(T) == []
    query, args = pool.fetches[0]
    assert "ORDER BY process_kind, observed_at DESC, instance_identity DESC" in query
    assert "LIMIT $2" in query
    assert args == (T, BIRTH_PROFILE_MAX_RETURNED_RECEIPTS)
