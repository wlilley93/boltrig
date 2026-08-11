"""In-memory durable-shape implementation for camera bindings and leases.

Camera rows deliberately do not share the device-root tables.  A camera lease
has a camera binding and a signed semantic action, never a filesystem root,
path, argv, or command executor.
"""

from __future__ import annotations

import copy
import secrets
from dataclasses import replace
from datetime import timedelta

from boltrig.camera_leases import CameraBinding, CameraLease
from boltrig.models import HITLStatus, HITLType, utcnow


class CameraStoreMem:
    async def upsert_camera_binding(self, binding: CameraBinding) -> bool:
        devices = getattr(self, "_devices", {})
        device = devices.get((binding.tenant_id, binding.device_id))
        if (
            device is None
            or device.owner_id != binding.owner_id
            or device.revoked_at is not None
        ):
            return False
        bindings, _ = _tables(self)
        bindings[(binding.tenant_id, binding.device_id, binding.camera_id)] = _copy_binding(binding)
        return True

    async def get_camera_binding(self, tenant_id, device_id, camera_id):
        bindings, _ = _tables(self)
        row = bindings.get((tenant_id, device_id, camera_id))
        return _copy_binding(row) if row is not None else None

    async def list_camera_bindings(self, tenant_id, owner_id, device_id=None):
        bindings, _ = _tables(self)
        rows = [
            _copy_binding(row)
            for (tenant, device, _), row in bindings.items()
            if tenant == tenant_id
            and row.owner_id == owner_id
            and (device_id is None or device == device_id)
        ]
        return sorted(rows, key=lambda row: (row.camera_id, row.device_id))

    async def create_camera_lease(self, lease: CameraLease) -> bool:
        devices = getattr(self, "_devices", {})
        bindings, leases = _tables(self)
        device = devices.get((lease.tenant_id, lease.device_id))
        binding = bindings.get((lease.tenant_id, lease.device_id, lease.camera_id))
        approval = await self.get_hitl_request(lease.tenant_id, lease.approval_id)
        response = await self.get_hitl_response(lease.tenant_id, lease.approval_id)
        duplicate_approval = any(
            row.tenant_id == lease.tenant_id and row.approval_id == lease.approval_id
            for row in leases.values()
        )
        now = utcnow()
        descriptor = lease.action.get("descriptor_fingerprint") if isinstance(lease.action, dict) else None
        if (
            device is None
            or device.owner_id != lease.owner_id
            or device.revoked_at is not None
            or device.lease_verify_key_id != lease.signing_key_id
            or binding is None
            or binding.owner_id != lease.owner_id
            or binding.connection_state != "connected"
            or binding.ptz_get_state not in {"readable", "proven"}
            or (lease.verb == "camera.ptz.set" and binding.ptz_set_state != "proven")
            or descriptor != binding.descriptor_fingerprint
            or approval is None
            or approval.status != HITLStatus.CONSUMED
            or approval.type != HITLType.APPROVAL
            or approval.verb != lease.verb
            or approval.action_digest is None
            or not secrets.compare_digest(approval.action_digest, lease.action_digest)
            or (approval.timeout_at is not None and approval.timeout_at <= now)
            or lease.owner_id not in {approval.requested_by, approval.requested_on_behalf_of}
            or response is None
            or response.respondent in {approval.requested_by, approval.requested_on_behalf_of}
            or response.decision.strip().lower() not in {"approve", "approved", "yes", "allow"}
            or _approval_run_cancelled(self, lease.tenant_id, lease.approval_id)
            or lease.status != "issued"
            or lease.expires_at <= now
            or lease.expires_at > now + timedelta(seconds=120)
            or (lease.tenant_id, lease.id) in leases
            or duplicate_approval
        ):
            return False
        leases[(lease.tenant_id, lease.id)] = _copy_lease(lease)
        return True

    async def get_camera_lease(self, tenant_id, device_id, lease_id):
        _, leases = _tables(self)
        row = leases.get((tenant_id, lease_id))
        return _copy_lease(row) if row is not None and row.device_id == device_id else None

    async def list_pending_camera_leases(self, tenant_id, device_id, limit=50):
        devices = getattr(self, "_devices", {})
        bindings, leases = _tables(self)
        now = utcnow()
        device = devices.get((tenant_id, device_id))
        rows = [
            _copy_lease(row)
            for (tenant, _), row in leases.items()
            if tenant == tenant_id
            and row.device_id == device_id
            and row.status == "issued"
            and row.expires_at >= now
            and device is not None
            and device.revoked_at is None
            and (binding := bindings.get((tenant_id, device_id, row.camera_id))) is not None
            and binding.connection_state == "connected"
            and not _approval_run_cancelled(self, tenant_id, row.approval_id)
        ]
        return sorted(rows, key=lambda row: (row.issued_at, row.id))[: max(1, min(int(limit), 50))]

    async def list_camera_leases_for_owner(self, tenant_id, owner_id, device_id, limit=50):
        devices = getattr(self, "_devices", {})
        _, leases = _tables(self)
        device = devices.get((tenant_id, device_id))
        if device is None or device.owner_id != owner_id:
            return None
        rows = [
            _copy_lease(row)
            for (tenant, _), row in leases.items()
            if tenant == tenant_id and row.device_id == device_id and row.owner_id == owner_id
        ]
        return sorted(rows, key=lambda row: (row.issued_at, row.id), reverse=True)[: max(1, min(int(limit), 50))]

    async def claim_camera_lease(
        self, tenant_id, device_id, lease_id, signature, claim_token_hash, claim_expires_at
    ):
        devices = getattr(self, "_devices", {})
        bindings, leases = _tables(self)
        row = leases.get((tenant_id, lease_id))
        device = devices.get((tenant_id, device_id))
        binding = bindings.get((tenant_id, device_id, row.camera_id)) if row is not None else None
        now = utcnow()
        if (
            row is None
            or row.device_id != device_id
            or row.status != "issued"
            or device is None
            or device.revoked_at is not None
            or binding is None
            or binding.connection_state != "connected"
            or _approval_run_cancelled(self, tenant_id, row.approval_id)
            or row.expires_at < now
            or claim_expires_at <= now
            or claim_expires_at > now + timedelta(minutes=5)
            or not secrets.compare_digest(row.signature, signature)
        ):
            return None
        row.status = "claimed"
        row.claim_token_hash = claim_token_hash
        row.claim_expires_at = claim_expires_at
        row.claimed_at = now
        return _copy_lease(row)

    async def settle_camera_lease(
        self, tenant_id, device_id, lease_id, claim_token_hash, status, receipt
    ):
        _, leases = _tables(self)
        row = leases.get((tenant_id, lease_id))
        now = utcnow()
        if (
            row is None
            or row.device_id != device_id
            or row.status != "claimed"
            or status not in {"completed", "failed"}
            or row.claim_token_hash is None
            or row.claim_expires_at is None
            or row.claim_expires_at < now
            or not secrets.compare_digest(row.claim_token_hash, claim_token_hash)
        ):
            return False
        row.status = status
        row.receipt = copy.deepcopy(receipt)
        row.settled_at = now
        row.claim_token_hash = None
        return True


def _copy_binding(binding):
    return replace(binding, capabilities=copy.deepcopy(binding.capabilities), evidence=copy.deepcopy(binding.evidence))


def _copy_lease(lease):
    return replace(lease, action=copy.deepcopy(lease.action), receipt=copy.deepcopy(lease.receipt))


def _approval_run_cancelled(store, tenant_id, approval_id):
    approval = getattr(store, "_hitl", {}).get((tenant_id, approval_id))
    return bool(
        approval is not None
        and approval.run_id
        and (tenant_id, approval.run_id) in getattr(store, "_cancels", {})
    )


def _tables(store):
    bindings = getattr(store, "_camera_bindings", None)
    leases = getattr(store, "_camera_leases", None)
    if bindings is None:
        bindings = {}
        setattr(store, "_camera_bindings", bindings)
    if leases is None:
        leases = {}
        setattr(store, "_camera_leases", leases)
    return bindings, leases
