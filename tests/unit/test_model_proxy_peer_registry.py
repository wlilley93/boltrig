from __future__ import annotations

import asyncio
from typing import cast

import pytest

from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyCellAlreadyRegistered,
    ModelProxyPeerRegistryCapacityExceeded,
    ModelProxyPeerRegistryError,
    ModelProxyProcessAlreadyRegistered,
    ModelProxyProcessRegistry,
    ModelProxyRegistrationState,
)

from .model_proxy_peer_fakes import DEFAULT_GID, DEFAULT_UID, cell_scope


@pytest.mark.unit
async def test_registration_is_exact_atomic_and_terminally_non_reusable() -> None:
    registry = ModelProxyProcessRegistry(max_cells=2)
    scope = cell_scope()

    registration = await registry.register(
        scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID
    )

    first_snapshot = await registry.snapshot_live()
    assert first_snapshot.version == 1
    assert first_snapshot.registrations == (registration,)
    assert await registry.confirm_snapshot_live(first_snapshot.version, registration)
    assert await registry.revoke(scope)
    assert not await registry.confirm_snapshot_live(first_snapshot.version, registration)
    terminal_snapshot = await registry.snapshot_live()
    assert terminal_snapshot.version == 2
    assert terminal_snapshot.registrations == ()
    assert not await registry.revoke(scope)
    assert (await registry.snapshot_live()).version == 3
    with pytest.raises(ModelProxyCellAlreadyRegistered):
        await registry.register(scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)


@pytest.mark.unit
async def test_concurrent_registration_collision_has_one_winner() -> None:
    registry = ModelProxyProcessRegistry()
    scope = cell_scope()

    results = await asyncio.gather(
        *(
            registry.register(scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)
            for _ in range(16)
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ModelProxyCellAlreadyRegistered) for result in results) == 15
    assert await registry.retained_count() == 1


@pytest.mark.unit
async def test_live_pid_and_exact_process_identity_cannot_alias_cells() -> None:
    registry = ModelProxyProcessRegistry()
    original = cell_scope()
    await registry.register(original, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)

    same_live_pid = cell_scope(cell_id="cell-2", assignment_id="assignment-2", start_ticks=20_001)
    with pytest.raises(ModelProxyProcessAlreadyRegistered):
        await registry.register(same_live_pid, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)

    assert await registry.revoke(original)
    exact_reuse = cell_scope(cell_id="cell-3", assignment_id="assignment-3")
    with pytest.raises(ModelProxyProcessAlreadyRegistered):
        await registry.register(exact_reuse, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)

    pid_reuse = cell_scope(cell_id="cell-4", assignment_id="assignment-4", start_ticks=20_002)
    replacement = await registry.register(
        pid_reuse, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID
    )
    assert replacement.state is ModelProxyRegistrationState.LIVE


@pytest.mark.unit
async def test_registry_retains_tombstones_and_fails_closed_at_capacity() -> None:
    """LIVE records fail closed at capacity; tombstones are bounded separately.

    A retained tombstone never consumes LIVE capacity and keeps its identity
    non-reusable; once the terminal bound is exceeded the OLDEST tombstone is
    evicted, making only that evicted identity reusable.
    """

    registry = ModelProxyProcessRegistry(max_cells=1, max_terminal_tombstones=1)
    first = cell_scope()
    await registry.register(first, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)
    assert await registry.revoke(first)

    # A retained tombstone does not consume LIVE capacity.
    second_scope = cell_scope(pid=201, cell_id="cell-2")
    second = await registry.register(
        second_scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID
    )
    assert second.state is ModelProxyRegistrationState.LIVE

    # LIVE capacity still fails closed.
    with pytest.raises(ModelProxyPeerRegistryCapacityExceeded):
        await registry.register(
            cell_scope(pid=202, cell_id="cell-3"),
            expected_uid=DEFAULT_UID,
            expected_gid=DEFAULT_GID,
        )

    # A retained tombstone still fails closed on identity reuse.
    with pytest.raises(ModelProxyCellAlreadyRegistered):
        await registry.register(first, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)

    # Exceeding the terminal bound evicts the oldest tombstone (``first``);
    # only that evicted identity becomes reusable, the retained one does not.
    assert await registry.revoke(second_scope)
    reincarnation = await registry.register(
        first, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID
    )
    assert reincarnation.state is ModelProxyRegistrationState.LIVE
    with pytest.raises(ModelProxyCellAlreadyRegistered):
        await registry.register(
            second_scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID
        )


@pytest.mark.unit
async def test_registration_repr_does_not_expose_scope_or_process_details() -> None:
    registry = ModelProxyProcessRegistry()
    registration = await registry.register(
        cell_scope(), expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID
    )

    rendered = repr(registration)
    assert "tenant-1" not in rendered
    assert "assignment-1" not in rendered
    assert "200" not in rendered
    assert "1001" not in rendered
    assert "redacted" in rendered
    assert repr(await registry.snapshot_live()) == "ModelProxyRegistrySnapshot(<redacted>)"


@pytest.mark.unit
async def test_any_register_or_revoke_invalidates_an_existing_snapshot() -> None:
    registry = ModelProxyProcessRegistry()
    first_scope = cell_scope()
    first = await registry.register(first_scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)
    snapshot = await registry.snapshot_live()

    await registry.register(
        cell_scope(pid=201, start_ticks=20_001, cell_id="cell-2", assignment_id="assignment-2"),
        expected_uid=DEFAULT_UID,
        expected_gid=DEFAULT_GID,
    )
    assert not await registry.confirm_snapshot_live(snapshot.version, first)

    second_snapshot = await registry.snapshot_live()
    assert await registry.revoke(first_scope)
    assert not await registry.confirm_snapshot_live(second_snapshot.version, first)


@pytest.mark.unit
@pytest.mark.parametrize("uid,gid", [(-1, 1), (1, -1), (2**32 - 1, 1), (1, True)])
async def test_registration_rejects_invalid_linux_ids(uid: object, gid: object) -> None:
    registry = ModelProxyProcessRegistry()
    with pytest.raises((TypeError, ValueError)):
        await registry.register(
            cell_scope(), expected_uid=cast(int, uid), expected_gid=cast(int, gid)
        )


@pytest.mark.unit
async def test_authorize_mints_only_while_the_registration_is_live() -> None:
    """Attested-then-revoked must not still yield a bearer (the issuance TOCTOU)."""

    registry = ModelProxyProcessRegistry()
    scope = cell_scope()
    await registry.register(scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)

    async def mint() -> str:
        return "bearer"

    assert await registry.authorize(scope, mint) == "bearer"
    assert await registry.revoke(scope)
    with pytest.raises(ModelProxyPeerRegistryError):
        await registry.authorize(scope, mint)


@pytest.mark.unit
async def test_authorize_refuses_an_unregistered_scope() -> None:
    registry = ModelProxyProcessRegistry()

    async def mint() -> str:  # pragma: no cover - must never run
        raise AssertionError("mint ran for an unregistered scope")

    with pytest.raises(ModelProxyPeerRegistryError):
        await registry.authorize(cell_scope(), mint)


@pytest.mark.unit
async def test_a_revoke_cannot_interleave_with_an_in_flight_mint() -> None:
    """revoke takes the same lock, so it cannot land mid-issuance."""

    registry = ModelProxyProcessRegistry()
    scope = cell_scope()
    await registry.register(scope, expected_uid=DEFAULT_UID, expected_gid=DEFAULT_GID)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def mint() -> str:
        entered.set()
        await release.wait()
        return "bearer"

    minting = asyncio.create_task(registry.authorize(scope, mint))
    await entered.wait()
    revoking = asyncio.create_task(registry.revoke(scope))
    await asyncio.sleep(0)
    assert not revoking.done()  # blocked on the registry lock the mint holds
    release.set()
    assert await minting == "bearer"
    assert await revoking
