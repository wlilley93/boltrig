"""Scoped-declarative capability reconciliation ([2026] LEXBY LOG-2026-07-17).

The fleet manifest is DECLARATIVE over the capabilities it authored and ADDITIVE
over governed control-plane grants. These tests bind SEC-171 and run against BOTH
stores (the Postgres leg RUNS under scripts/with_test_postgres.sh, it does not
skip when the DSN is set).
"""

from __future__ import annotations

import os
import uuid

import pytest

from boltrig.config import apply_manifest
from boltrig.config.manifest import EphemeralRuntime, FleetManifest
from boltrig.config.manifest_reconcile import BulkCapabilityDeactivationError
from boltrig.fleet.spawn_skills import NoCapableRuntime, select_capability
from boltrig.kernel import Kernel
from boltrig.models import AgentCapability
from boltrig.store import InMemoryStore

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")

pytestmark = pytest.mark.store


@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield InMemoryStore()
        return
    if not DSN:
        pytest.skip("set BOLTRIG_TEST_DATABASE_URL for the Postgres leg")
    from boltrig.store import PostgresStore

    pg = await PostgresStore.connect(DSN)
    try:
        yield pg
    finally:
        await pg.close()


def _runtimes(*specs: tuple[str, tuple[str, ...]]) -> tuple[EphemeralRuntime, ...]:
    return tuple(EphemeralRuntime(name=n, supported_skills=sk) for n, sk in specs)


def _manifest(tenant, runtimes, *, reconcile=None) -> FleetManifest:
    extra = {"reconcile": reconcile} if reconcile is not None else {}
    return FleetManifest(
        organisation=tenant, tenant_id=tenant, ephemeral_runtimes=runtimes, extra=extra
    )


async def _apply(store, manifest, **kw) -> None:
    await apply_manifest(Kernel(store), manifest, **kw)


async def _names(store, tenant) -> set[str]:
    return {c.name for c in await store.list_capabilities(tenant)}


async def _upsert_control_plane(store, tenant, name, skills=("*",)) -> None:
    await store.upsert_capability(
        AgentCapability(
            name=name, tenant_id=tenant, runtime="openai",
            supported_skills=list(skills), max_depth=1, is_ephemeral=True,
            cost_tier="cheap", source="control-plane",
        )
    )


@pytest.mark.invariant("SEC-171")
async def test_dropped_manifest_capability_deactivates_and_stops_routing(store):
    tenant = f"t-{uuid.uuid4().hex}"
    await _apply(store, _manifest(tenant, _runtimes(
        ("worker-a", ("general/*",)), ("worker-b", ("special/*",)),
    )))
    assert await _names(store, tenant) == {"worker-a", "worker-b"}
    # worker-b is the only capability that supports the 'special/*' skill.
    picked = await select_capability(store, tenant, ["special/task"], {})
    assert picked.name == "worker-b"

    # Redeploy WITHOUT worker-b: it is soft-deactivated.
    await _apply(store, _manifest(tenant, _runtimes(("worker-a", ("general/*",)))))
    assert await _names(store, tenant) == {"worker-a"}
    all_names = {c.name for c in await store.list_all_capabilities(tenant)}
    assert all_names == {"worker-a", "worker-b"}  # the row survives, just inactive
    # ... and it can no longer be routed to.
    with pytest.raises(NoCapableRuntime):
        await select_capability(store, tenant, ["special/task"], {})


@pytest.mark.invariant("SEC-171")
async def test_control_plane_capability_survives_a_manifest_that_omits_it(store):
    tenant = f"t-{uuid.uuid4().hex}"
    await _upsert_control_plane(store, tenant, "governed-x")
    await _apply(store, _manifest(tenant, _runtimes(
        ("worker-a", ("*",)), ("worker-b", ("*",)),
    )))
    # Redeploy dropping worker-b; the manifest never mentions the governed grant.
    await _apply(store, _manifest(tenant, _runtimes(("worker-a", ("*",)))))
    active = {c.name for c in await store.list_capabilities(tenant)}
    assert active == {"worker-a", "governed-x"}  # worker-b dropped, governed-x kept
    governed = next(
        c for c in await store.list_all_capabilities(tenant) if c.name == "governed-x"
    )
    assert governed.source == "control-plane" and governed.is_active is True


@pytest.mark.invariant("SEC-171")
async def test_name_from_both_paths_becomes_manifest_and_reconciles(store):
    tenant = f"t-{uuid.uuid4().hex}"
    await _upsert_control_plane(store, tenant, "dual")
    # The manifest re-declares 'dual': it reclaims ownership (source -> manifest).
    await _apply(store, _manifest(tenant, _runtimes(
        ("dual", ("*",)), ("keep", ("*",)),
    )))
    dual = next(
        c for c in await store.list_all_capabilities(tenant) if c.name == "dual"
    )
    assert dual.source == "manifest" and dual.is_active is True

    # Now that it is manifest-sourced, dropping it reconciles it away.
    await _apply(store, _manifest(tenant, _runtimes(("keep", ("*",)))))
    assert await _names(store, tenant) == {"keep"}
    dual = next(
        c for c in await store.list_all_capabilities(tenant) if c.name == "dual"
    )
    assert dual.is_active is False


@pytest.mark.invariant("SEC-WRK-12")
async def test_governed_status_and_status_preserving_edits_match_both_stores(store):
    tenant = f"t-{uuid.uuid4().hex}"
    await _upsert_control_plane(store, tenant, "recoverable")
    retired = await store.set_capability_active(tenant, "recoverable", False)
    assert retired is not None and retired.is_active is False
    await store.upsert_capability(
        AgentCapability(
            name="recoverable",
            tenant_id=tenant,
            runtime="codex",
            supported_skills=["*"],
            max_depth=2,
            is_ephemeral=False,
            cost_tier="standard",
            source="control-plane",
        ),
        preserve_status=True,
    )
    assert await store.list_capabilities(tenant) == []
    edited = (await store.list_all_capabilities(tenant))[0]
    assert edited.runtime == "codex" and edited.is_active is False
    restored = await store.set_capability_active(tenant, "recoverable", True)
    assert restored is not None and restored.is_active is True


@pytest.mark.invariant("SEC-171")
async def test_empty_manifest_aborts_without_confirm_and_succeeds_with_it(store):
    tenant = f"t-{uuid.uuid4().hex}"
    await _apply(store, _manifest(tenant, _runtimes(
        ("a", ("*",)), ("b", ("*",)), ("c", ("*",)),
    )))
    # An empty manifest ABORTS unconditionally, with nothing committed.
    with pytest.raises(BulkCapabilityDeactivationError):
        await _apply(store, _manifest(tenant, ()))
    assert await _names(store, tenant) == {"a", "b", "c"}
    # The explicit confirm overrides it: every manifest-sourced cap deactivates.
    await _apply(store, _manifest(tenant, ()), confirm_bulk_deactivate=True)
    assert await _names(store, tenant) == set()


@pytest.mark.invariant("SEC-171")
async def test_over_threshold_drop_aborts_without_confirm_and_succeeds_with_it(store):
    tenant = f"t-{uuid.uuid4().hex}"
    original = _runtimes(*[(f"cap-{i}", ("*",)) for i in range(10)])
    await _apply(store, _manifest(tenant, original))
    # Dropping 8 of 10 (> max(3, 5)) trips the guard; the two NEW caps in the
    # redeploy must NOT be committed (the whole apply aborts before any write).
    redeploy = _runtimes(("fresh-x", ("*",)), ("fresh-y", ("*",)))
    with pytest.raises(BulkCapabilityDeactivationError):
        await _apply(store, _manifest(tenant, redeploy))
    all_names = {c.name for c in await store.list_all_capabilities(tenant)}
    assert all_names == {f"cap-{i}" for i in range(10)}  # no fresh-* written
    assert "fresh-x" not in all_names and "fresh-y" not in all_names

    # The manifest-field override also works and lets the drop through.
    await _apply(
        store, _manifest(tenant, redeploy, reconcile={"allow_bulk_deactivate": True})
    )
    assert await _names(store, tenant) == {"fresh-x", "fresh-y"}
