from datetime import timedelta

import pytest

from boltrig.camera_leases import CameraBinding, CameraLease, CameraLeaseIssuer
from boltrig.kernel.device_crypto import DeviceLeaseSigner
from boltrig.models import HITLStatus, HITLType, utcnow
from boltrig.models.camera_actions import canonical_camera_action


CAMERA_ID = "camera_" + "a" * 32
FINGERPRINT = "b" * 64


def test_camera_action_digest_is_exact_and_has_no_root_or_command_surface():
    action, digest = canonical_camera_action(
        "device_1",
        CAMERA_ID,
        "camera.ptz.set",
        {
            "descriptor_fingerprint": FINGERPRINT,
            "pan_millidegrees": 1,
            "tilt_millidegrees": -1,
        },
    )
    assert action["pan_millidegrees"] == 1
    assert len(digest) == 64
    with pytest.raises(ValueError, match="unknown_camera_action_field"):
        canonical_camera_action(
            "device_1",
            CAMERA_ID,
            "camera.ptz.set",
            {
                "descriptor_fingerprint": FINGERPRINT,
                "pan_millidegrees": 1,
                "tilt_millidegrees": -1,
                "root_id": "root_1",
            },
        )


def test_camera_lease_is_not_a_device_root_lease():
    now = utcnow()
    lease = CameraLease(
        id="lease_1",
        tenant_id="tenant",
        device_id="device_1",
        camera_id=CAMERA_ID,
        owner_id="alice",
        verb="camera.ptz.get",
        action={"descriptor_fingerprint": FINGERPRINT},
        action_digest="c" * 64,
        approval_id="approval_1",
        issued_at=now,
        expires_at=now + timedelta(seconds=120),
    )
    assert "root_id" not in lease.canonical_payload()
    signed = DeviceLeaseSigner.from_seed(b"c" * 32).sign(lease)
    assert signed.signature
    assert signed.signing_key_id


class _Store:
    def __init__(self):
        self.lease = None
        self.request = type(
            "Request",
            (),
            {
                "status": HITLStatus.CONSUMED,
                "type": HITLType.APPROVAL,
                "verb": "camera.ptz.set",
                "action_digest": None,
                "requested_by": "alice",
                "requested_on_behalf_of": None,
                "timeout_at": None,
            },
        )()
        self.response = type(
            "Response",
            (),
            {"respondent": "reviewer", "decision": "approve"},
        )()

    async def get_camera_binding(self, tenant_id, device_id, camera_id):
        return CameraBinding(
            device_id=device_id,
            camera_id=camera_id,
            descriptor_fingerprint=FINGERPRINT,
            owner_id="alice",
            connection_state="connected",
            ptz_get_state="proven",
            ptz_set_state="proven",
        )

    async def get_hitl_request(self, tenant_id, request_id):
        return self.request

    async def get_hitl_response(self, tenant_id, request_id):
        return self.response

    async def create_camera_lease(self, lease):
        self.lease = lease
        return True


@pytest.mark.asyncio
async def test_camera_lease_issuer_binds_descriptor_and_requires_proven_ptz():
    store = _Store()
    action, digest = canonical_camera_action(
        "device_1",
        CAMERA_ID,
        "camera.ptz.set",
        {
            "descriptor_fingerprint": FINGERPRINT,
            "pan_millidegrees": 36_000,
            "tilt_millidegrees": 0,
        },
    )
    store.request.action_digest = digest
    issuer = CameraLeaseIssuer(store, DeviceLeaseSigner.from_seed(b"d" * 32))
    lease = await issuer.materialize(
        tenant_id="tenant",
        owner_id="alice",
        device_id="device_1",
        camera_id=CAMERA_ID,
        verb="camera.ptz.set",
        raw_action=action,
        approval_id="approval_1",
        approved_by="reviewer",
    )
    assert lease.camera_id == CAMERA_ID
    assert not hasattr(lease, "root_id")
    assert store.lease is lease
