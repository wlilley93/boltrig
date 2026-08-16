from datetime import timedelta
import re

import pytest

from boltrig.adapters.builtin.camera_leases import camera_lease_specs
from boltrig.camera_leases import CameraBinding, CameraLeaseIssuer
from boltrig.kernel.device_crypto import DeviceLeaseSigner, mint_scoped_token, token_digest
from boltrig.models import HITLStatus, HITLType, utcnow
from boltrig.models.devices import EnrolledDevice
from boltrig.store import InMemoryStore
from boltrig.store.camera_pg import CameraStorePG


TENANT = "camera-tenant"
DEVICE = "device_camera"
CAMERA = "camera_" + "a" * 32
FINGERPRINT = "b" * 64


@pytest.mark.asyncio
async def test_camera_binding_and_lease_transport_has_no_root_surface():
    store = InMemoryStore()
    store._devices = {}
    store._hitl = {}
    store._hitl_resp = {}
    store._cancels = {}
    signer = DeviceLeaseSigner.from_seed(b"u" * 32)
    token = mint_scoped_token("device_session", TENANT, DEVICE)
    store._devices[(TENANT, DEVICE)] = EnrolledDevice(
        id=DEVICE,
        tenant_id=TENANT,
        owner_id="alice",
        label="Worker",
        public_key="public",
        public_key_fingerprint="f" * 64,
        lease_verify_key_id=signer.key_id,
        session_token_hash=token_digest(token),
        session_expires_at=utcnow() + timedelta(hours=1),
    )
    binding = CameraBinding(
        tenant_id=TENANT,
        device_id=DEVICE,
        camera_id=CAMERA,
        descriptor_fingerprint=FINGERPRINT,
        owner_id="alice",
        connection_state="connected",
        ptz_get_state="proven",
        ptz_set_state="proven",
    )
    assert await store.upsert_camera_binding(binding)
    issuer = CameraLeaseIssuer(store, signer)
    action = {"descriptor_fingerprint": FINGERPRINT, "pan_millidegrees": 36000, "tilt_millidegrees": 0}
    _, digest = await _action_digest(issuer, action)
    request = type(
        "Request",
        (),
        {
            "status": HITLStatus.CONSUMED,
            "type": HITLType.APPROVAL,
            "verb": "camera.ptz.set",
            "action_digest": digest,
            "requested_by": "alice",
            "requested_on_behalf_of": None,
            "timeout_at": None,
            "run_id": None,
        },
    )()
    response = type(
        "Response",
        (),
        {
            "tenant_id": TENANT,
            "request_id": "approval_camera",
            "respondent": "reviewer",
            "decision": "approve",
            "responded_at": utcnow(),
        },
    )()
    store._hitl[(TENANT, "approval_camera")] = request
    store._hitl_resp[(TENANT, "approval_camera")] = response
    lease = await issuer.materialize(
        tenant_id=TENANT,
        owner_id="alice",
        device_id=DEVICE,
        camera_id=CAMERA,
        verb="camera.ptz.set",
        raw_action=action,
        approval_id="approval_camera",
        approved_by="reviewer",
    )
    pending = await store.list_pending_camera_leases(TENANT, DEVICE)
    assert [row.id for row in pending] == [lease.id]
    claimed = await store.claim_camera_lease(
        TENANT, DEVICE, lease.id, lease.signature, "c" * 64, utcnow() + timedelta(minutes=1)
    )
    assert claimed is not None
    assert await store.settle_camera_lease(
        TENANT, DEVICE, lease.id, "c" * 64, "completed", {"code": "camera_uvc_completed"}
    )
    assert "root_id" not in lease.canonical_payload()


async def _action_digest(issuer, action):
    context = await issuer.resource_context(
        TENANT, "alice", DEVICE, CAMERA, "camera.ptz.set", action
    )
    return context["action_digest"], context["action_digest"]


def test_camera_lease_specs_are_dynamic_and_root_free():
    specs = {spec.verb_id: spec for spec in camera_lease_specs()}
    assert set(specs) == {"camera.ptz.get", "camera.ptz.set"}
    for spec in specs.values():
        assert "root_id" not in spec.input_schema.get("properties", {})


@pytest.mark.asyncio
async def test_postgres_camera_binding_uses_one_argument_for_each_placeholder():
    class StrictPool:
        async def execute(self, query, *args):
            placeholders = {int(value) for value in re.findall(r"\$(\d+)", query)}
            assert placeholders == set(range(1, len(args) + 1))
            assert args[4] == "connected"
            assert args[14] == "alice"
            return "INSERT 0 1"

    store = CameraStorePG()
    store._pool = StrictPool()
    binding = CameraBinding(
        tenant_id=TENANT,
        device_id=DEVICE,
        camera_id=CAMERA,
        descriptor_fingerprint=FINGERPRINT,
        owner_id="alice",
        connection_state="connected",
        ptz_get_state="proven",
        ptz_set_state="proven",
    )

    assert await store.upsert_camera_binding(binding)
