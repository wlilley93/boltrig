"""The desktop install census, and the disclosure fence on it (A4).

``devices`` has been a real install ledger since the desktop began auto-enrolling
on sign-in, but both ``list_devices`` implementations hard-filter to the caller's
own ``owner_id``, so no administrator could read it. These are the contracts for
the read that was missing.

The two-orgs-one-laptop case is the one worth seeding. Enrolment happens under
the active org and ``public_key_fingerprint`` is per-keychain, so one machine can
hold two seats. A census that reported only seats would say two laptops.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import utcnow
from boltrig.models.devices import DeviceEnrollment, EnrolledDevice
from boltrig.store import InMemoryStore

T = "device-census"


def _device(
    device_id: str, owner_id: str, fingerprint: str, *, tenant_id: str = T
) -> EnrolledDevice:
    return EnrolledDevice(
        id=device_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        label="Boltrig Desktop",
        public_key=f"pk-{device_id}",
        public_key_fingerprint=fingerprint,
        lease_verify_key_id="verify-1",
        last_seen_at=utcnow(),
    )


async def _enrol(store: InMemoryStore, device: EnrolledDevice) -> None:
    """Seed through the REAL enrolment path, not by writing the table.

    A census seeded by hand is a census of a shape nobody produces; going
    through create/complete is what proves the counted rows are the rows the
    desktop actually creates.
    """
    code_hash = sha256(f"{device.tenant_id}:{device.id}".encode()).hexdigest()
    assert await store.create_device_enrollment(
        DeviceEnrollment(
            id=f"enrol-{device.id}",
            tenant_id=device.tenant_id,
            owner_id=device.owner_id,
            label=device.label,
            authorization_code_hash=code_hash,
            expires_at=utcnow() + timedelta(minutes=5),
        )
    )
    assert await store.complete_device_enrollment(
        device.tenant_id, f"enrol-{device.id}", code_hash, device
    ) is not None


async def _seeded() -> InMemoryStore:
    store = InMemoryStore()
    for device in (
        # Alice on two machines.
        _device("d1", "alice", "fp-laptop"),
        _device("d2", "alice", "fp-desktop"),
        # Bob's ONE laptop, enrolled twice because he belongs to two orgs. Two
        # seats, one machine: the whole reason both numbers are reported.
        _device("d3", "bob", "fp-bob-laptop"),
        _device("d4", "bob", "fp-bob-laptop"),
        # A machine that was uninstalled: a record that something WAS installed.
        _device("d5", "carol", "fp-carol"),
        # Another tenant entirely.
        _device("d6", "mallory", "fp-other", tenant_id="other-tenant"),
    ):
        await _enrol(store, device)
    assert await store.revoke_device(T, "d5", "carol")
    return store


def _headers(role: str = "admin") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "auditor",
        "x-boltrig-role": role,
    }


@pytest.mark.security
async def test_the_census_reports_seats_machines_and_users_separately() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    body = client.get("/v1/admin/devices", headers=_headers()).json()

    assert body["users_with_desktop"] == 2  # alice and bob; carol revoked
    assert body["live_installs"] == 4  # d1 d2 d3 d4
    # THE GAP. Four seats, three machines, because bob's one laptop holds two.
    # An assertion on seats alone would have been satisfied by a census that
    # cannot tell a second org from a second computer.
    assert body["distinct_machines"] == 3
    assert body["revoked_installs"] == 1

    rollup = {row["owner_id"]: row for row in body["owners"]}
    assert rollup["alice"]["live_installs"] == 2
    assert rollup["alice"]["distinct_machines"] == 2
    assert rollup["bob"]["live_installs"] == 2
    assert rollup["bob"]["distinct_machines"] == 1
    assert rollup["carol"]["live_installs"] == 0
    assert rollup["carol"]["revoked_installs"] == 1
    # The other tenant's row is absent, not merely uncounted.
    assert "mallory" not in rollup


@pytest.mark.security
async def test_the_census_returns_no_key_or_session_material() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    raw = client.get("/v1/admin/devices", headers=_headers()).text
    for secret in ("pk-d1", "public_key", "session_token_hash", "verify-1"):
        assert secret not in raw
    # The negative control: the fields it DOES carry are really there, so the
    # four absences above are absences rather than an empty response.
    assert "alice" in raw and "distinct_machines" in raw


@pytest.mark.security
async def test_a_non_author_cannot_read_the_census() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    assert client.get("/v1/admin/devices", headers=_headers("member")).status_code == 403
    assert client.get("/v1/admin/devices", headers=_headers("viewer")).status_code == 403
    assert client.get("/v1/admin/devices", headers=_headers("admin")).status_code == 200


@pytest.mark.security
async def test_the_owner_scoped_read_is_unchanged_by_the_tenant_read() -> None:
    store = await _seeded()
    assert [row.id for row in await store.list_devices(T, "alice")] == ["d1", "d2"]
    assert [row.id for row in await store.list_devices_for_tenant(T)] == [
        "d1", "d2", "d3", "d4", "d5",
    ]
