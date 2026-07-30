"""Memory/Postgres parity for enrolled devices and single-use leases."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta

import pytest

from boltrig.kernel.device_crypto import DeviceLeaseSigner, token_digest
from boltrig.models import (
    HITLRequest,
    HITLResponse,
    HITLType,
    Urgency,
    utcnow,
)
from boltrig.models.devices import (
    DeviceEnrollment,
    DeviceLease,
    DeviceRoot,
    EnrolledDevice,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "device-store-tenant"
SIGNER = DeviceLeaseSigner.from_seed(b"p" * 32)


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE device_leases,device_roots,devices,device_enrollments,"
        "hitl_responses,hitl_requests,run_cancel_requests "
        "RESTART IDENTITY CASCADE"
    )
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
async def device_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _device(now) -> EnrolledDevice:
    return EnrolledDevice(
        id="device-1",
        tenant_id=T,
        owner_id="untrusted-placeholder",
        label="untrusted-placeholder",
        public_key="c" * 43,
        public_key_fingerprint="f" * 64,
        lease_verify_key_id=SIGNER.key_id,
        session_token_hash=token_digest("session-secret"),
        session_expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )


async def _approval(store, approval_id: str, verb: str) -> None:
    await store.create_hitl_request(
        HITLRequest(
            id=approval_id,
            tenant_id=T,
            run_id=f"run-{approval_id}",
            type=HITLType.APPROVAL,
            urgency=Urgency.BLOCKING,
            context="device",
            question="Approve?",
            verb=verb,
            requested_by="alice",
            request_fingerprint=f"fingerprint-{approval_id}",
            action_digest="a" * 64,
        )
    )
    assert await store.answer_hitl(
        HITLResponse(
            id=f"response-{approval_id}",
            request_id=approval_id,
            tenant_id=T,
            decision="approve",
            respondent="reviewer",
            responded_at=utcnow(),
        )
    ) is not None
    assert await store.consume_hitl(T, approval_id)


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-07")
@pytest.mark.invariant("SEC-08")
async def test_device_lifecycle_and_lease_cas_match_on_both_stores(device_store):
    now = utcnow()
    enrollment = DeviceEnrollment(
        id="enrollment-1",
        tenant_id=T,
        owner_id="alice",
        label="Alice laptop",
        authorization_code_hash=token_digest("enrollment-secret"),
        expires_at=now + timedelta(minutes=5),
        created_at=now,
    )
    assert await device_store.create_device_enrollment(enrollment)
    assert not await device_store.create_device_enrollment(enrollment)
    assert await device_store.complete_device_enrollment(
        T,
        enrollment.id,
        token_digest("wrong"),
        _device(now),
    ) is None
    completed = await device_store.complete_device_enrollment(
        T,
        enrollment.id,
        token_digest("enrollment-secret"),
        _device(now),
    )
    assert completed is not None
    assert completed.owner_id == "alice" and completed.label == "Alice laptop"
    assert await device_store.complete_device_enrollment(
        T,
        enrollment.id,
        token_digest("enrollment-secret"),
        replace(_device(now), id="device-replay"),
    ) is None
    assert await device_store.get_device("rival", completed.id) is None
    assert [row.id for row in await device_store.list_devices(T, "alice")] == [
        completed.id
    ]
    assert await device_store.authenticate_device_session(
        T, completed.id, token_digest("session-secret")
    ) is not None

    root = DeviceRoot(
        id="root-1",
        tenant_id=T,
        device_id=completed.id,
        label="Chosen workspace",
        scope="read_write",
    )
    assert await device_store.create_device_root(root, "alice")
    assert not await device_store.create_device_root(
        replace(root, id="mallory-root"), "mallory"
    )
    assert [row.id for row in await device_store.list_device_roots(
        T, completed.id
    )] == [root.id]

    await _approval(device_store, "approval-read", "device.file.read")
    lease = SIGNER.sign(
        DeviceLease(
            id="lease-1",
            tenant_id=T,
            device_id=completed.id,
            root_id=root.id,
            owner_id="alice",
            verb="device.file.read",
            action={"relative_path": "report.txt", "max_bytes": 100},
            action_digest="a" * 64,
            approval_id="approval-read",
            issued_at=now,
            expires_at=now + timedelta(minutes=2),
        )
    )
    assert await device_store.create_device_lease(lease)
    lease.action["relative_path"] = "caller-mutated.txt"
    stored_copy = await device_store.get_device_lease(T, completed.id, lease.id)
    assert stored_copy is not None
    assert stored_copy.action["relative_path"] == "report.txt"
    stored_copy.action["relative_path"] = "reader-mutated.txt"
    stored_again = await device_store.get_device_lease(T, completed.id, lease.id)
    assert stored_again is not None
    assert stored_again.action["relative_path"] == "report.txt"
    assert not await device_store.create_device_lease(
        replace(lease, id="lease-duplicate-approval")
    )
    assert await device_store.get_device_lease(
        "rival", completed.id, lease.id
    ) is None
    assert [row.id for row in await device_store.list_pending_device_leases(
        T, completed.id
    )] == [lease.id]
    owner_rows = await device_store.list_device_leases_for_owner(
        T, "alice", completed.id
    )
    assert owner_rows is not None and [row.id for row in owner_rows] == [lease.id]
    assert await device_store.list_device_leases_for_owner(
        T, "mallory", completed.id
    ) is None
    assert await device_store.list_device_leases_for_owner(
        "rival", "alice", completed.id
    ) is None

    claimed = await device_store.claim_device_lease(
        T,
        completed.id,
        lease.id,
        lease.signature,
        token_digest("claim-secret"),
        now + timedelta(minutes=5),
    )
    assert claimed is not None and claimed.status == "claimed"
    assert await device_store.claim_device_lease(
        T,
        completed.id,
        lease.id,
        lease.signature,
        token_digest("second-claim"),
        now + timedelta(minutes=5),
    ) is None
    assert not await device_store.settle_device_lease(
        T,
        completed.id,
        lease.id,
        token_digest("wrong"),
        "completed",
        {},
    )
    assert not await device_store.settle_device_lease(
        T,
        completed.id,
        lease.id,
        token_digest("claim-secret"),
        "issued",
        {},
    )
    assert await device_store.settle_device_lease(
        T,
        completed.id,
        lease.id,
        token_digest("claim-secret"),
        "completed",
        {"bytes": 4},
    )
    assert not await device_store.settle_device_lease(
        T,
        completed.id,
        lease.id,
        token_digest("claim-secret"),
        "completed",
        {},
    )
    settled = await device_store.get_device_lease(T, completed.id, lease.id)
    assert settled is not None
    assert settled.status == "completed" and settled.receipt == {"bytes": 4}
    assert settled.claim_token_hash is None
    owner_rows = await device_store.list_device_leases_for_owner(
        T, "alice", completed.id
    )
    assert owner_rows is not None
    assert owner_rows[0].status == "completed"
    assert owner_rows[0].receipt == {"bytes": 4}

    await _approval(device_store, "approval-cancelled", "device.file.read")
    cancelled = SIGNER.sign(
        replace(
            lease,
            id="lease-cancelled",
            approval_id="approval-cancelled",
            action={"relative_path": "cancelled.txt", "max_bytes": 100},
        )
    )
    assert await device_store.create_device_lease(cancelled)
    await device_store.request_run_cancel(
        T, "run-approval-cancelled", "alice"
    )
    assert cancelled.id not in {
        row.id
        for row in await device_store.list_pending_device_leases(T, completed.id)
    }
    assert await device_store.claim_device_lease(
        T,
        completed.id,
        cancelled.id,
        cancelled.signature,
        token_digest("cancelled-claim"),
        now + timedelta(minutes=5),
    ) is None

    await _approval(device_store, "approval-command", "device.command.run")
    command = SIGNER.sign(
        replace(
            lease,
            id="lease-command",
            approval_id="approval-command",
            verb="device.command.run",
            action={"argv": ["git", "status"], "timeout_seconds": 30},
        )
    )
    assert not await device_store.create_device_lease(command)
    await _approval(device_store, "approval-revoked-root", "device.file.read")
    outstanding = SIGNER.sign(
        replace(
            lease,
            id="lease-revoked-root",
            approval_id="approval-revoked-root",
            action={"relative_path": "still-pending.txt", "max_bytes": 100},
        )
    )
    assert await device_store.create_device_lease(outstanding)
    assert await device_store.revoke_device_root(
        T, completed.id, root.id, "alice"
    )
    assert await device_store.list_pending_device_leases(T, completed.id) == []
    assert await device_store.claim_device_lease(
        T,
        completed.id,
        outstanding.id,
        outstanding.signature,
        token_digest("claim-after-revoke"),
        utcnow() + timedelta(minutes=5),
    ) is None
    assert not await device_store.revoke_device_root(
        T, completed.id, root.id, "alice"
    )
    assert await device_store.revoke_device(T, completed.id, "alice")
    assert await device_store.authenticate_device_session(
        T, completed.id, token_digest("session-secret")
    ) is None
