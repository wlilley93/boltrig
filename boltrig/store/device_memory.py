"""In-memory reference implementation for enrolled devices and leases."""

from __future__ import annotations

import copy
import secrets
from dataclasses import replace
from datetime import timedelta

from boltrig.models import HITLStatus, HITLType, utcnow


class DeviceStoreMem:
    async def create_device_enrollment(self, enrollment):
        enrollments, _, _, _ = _tables(self)
        key = (enrollment.tenant_id, enrollment.id)
        if key in enrollments:
            return False
        enrollments[key] = replace(enrollment)
        return True

    async def complete_device_enrollment(
        self, tenant_id, enrollment_id, authorization_code_hash, device
    ):
        enrollments, devices, _, _ = _tables(self)
        enrollment = enrollments.get((tenant_id, enrollment_id))
        now = utcnow()
        if (
            enrollment is None or enrollment.consumed_at is not None
            or enrollment.expires_at < now
            or not secrets.compare_digest(
                enrollment.authorization_code_hash, authorization_code_hash
            )
        ):
            return None
        enrollment.consumed_at = now
        completed = replace(
            device, owner_id=enrollment.owner_id, label=enrollment.label
        )
        devices[(tenant_id, completed.id)] = replace(completed)
        return completed

    async def get_device(self, tenant_id, device_id):
        _, devices, _, _ = _tables(self)
        row = devices.get((tenant_id, device_id))
        return replace(row) if row else None

    async def list_devices(self, tenant_id, owner_id):
        _, devices, _, _ = _tables(self)
        rows = [
            replace(row) for (tenant, _), row in devices.items()
            if tenant == tenant_id and row.owner_id == owner_id
        ]
        return sorted(rows, key=lambda row: (row.created_at, row.id))

    async def list_devices_for_tenant(self, tenant_id):
        _, devices, _, _ = _tables(self)
        rows = [
            replace(row) for (tenant, _), row in devices.items()
            if tenant == tenant_id
        ]
        return sorted(rows, key=lambda row: (row.owner_id, row.created_at, row.id))

    async def authenticate_device_session(
        self, tenant_id, device_id, token_hash
    ):
        _, devices, _, _ = _tables(self)
        row = devices.get((tenant_id, device_id))
        now = utcnow()
        if (
            row is None or row.revoked_at is not None
            or row.session_token_hash is None or row.session_expires_at is None
            or row.session_expires_at < now
            or not secrets.compare_digest(row.session_token_hash, token_hash)
        ):
            return None
        row.last_seen_at = now
        row.presence = "online"
        row.updated_at = now
        return replace(row)

    async def rotate_device_session(
        self, tenant_id, device_id, old_hash, new_hash, expires_at
    ):
        authenticated = await self.authenticate_device_session(
            tenant_id, device_id, old_hash
        )
        if authenticated is None:
            return False
        _, devices, _, _ = _tables(self)
        row = devices[(tenant_id, device_id)]
        row.session_token_hash = new_hash
        row.session_expires_at = expires_at
        row.updated_at = utcnow()
        return True

    async def revoke_device(self, tenant_id, device_id, owner_id):
        _, devices, _, _ = _tables(self)
        row = devices.get((tenant_id, device_id))
        if row is None or row.owner_id != owner_id or row.revoked_at is not None:
            return False
        row.revoked_at = utcnow()
        row.presence = "revoked"
        row.session_token_hash = None
        row.session_expires_at = None
        return True

    async def create_device_root(self, root, owner_id):
        _, devices, roots, _ = _tables(self)
        device = devices.get((root.tenant_id, root.device_id))
        key = (root.tenant_id, root.id)
        if (
            device is None or device.owner_id != owner_id
            or device.revoked_at is not None or key in roots
        ):
            return False
        roots[key] = replace(root)
        return True

    async def list_device_roots(self, tenant_id, device_id):
        _, _, roots, _ = _tables(self)
        rows = [
            replace(row) for (tenant, _), row in roots.items()
            if tenant == tenant_id and row.device_id == device_id
            and row.revoked_at is None
        ]
        return sorted(rows, key=lambda row: (row.created_at, row.id))

    async def revoke_device_root(
        self, tenant_id, device_id, root_id, owner_id
    ):
        _, devices, roots, _ = _tables(self)
        device = devices.get((tenant_id, device_id))
        root = roots.get((tenant_id, root_id))
        if (
            device is None or device.owner_id != owner_id or root is None
            or root.device_id != device_id or root.revoked_at is not None
        ):
            return False
        root.revoked_at = utcnow()
        return True

    async def create_device_lease(self, lease):
        _, devices, roots, leases = _tables(self)
        device = devices.get((lease.tenant_id, lease.device_id))
        root = roots.get((lease.tenant_id, lease.root_id))
        approval = await self.get_hitl_request(
            lease.tenant_id, lease.approval_id
        )
        response = await self.get_hitl_response(
            lease.tenant_id, lease.approval_id
        )
        duplicate_approval = any(
            row.tenant_id == lease.tenant_id
            and row.approval_id == lease.approval_id
            for row in leases.values()
        )
        now = utcnow()
        if (
            device is None or device.owner_id != lease.owner_id
            or device.revoked_at is not None or root is None
            or device.lease_verify_key_id != lease.signing_key_id
            or root.device_id != lease.device_id or root.revoked_at is not None
            or approval is None or approval.status != HITLStatus.CONSUMED
            or approval.type != HITLType.APPROVAL
            or approval.verb != lease.verb
            or approval.action_digest is None
            or not secrets.compare_digest(
                approval.action_digest, lease.action_digest
            )
            or (
                approval.timeout_at is not None
                and approval.timeout_at <= utcnow()
            )
            or lease.owner_id not in {
                approval.requested_by, approval.requested_on_behalf_of
            }
            or response is None
            or response.respondent in {
                approval.requested_by, approval.requested_on_behalf_of
            }
            or response.decision.strip().lower()
            not in {"approve", "approved", "yes", "allow"}
            or (
                lease.verb == "device.file.write"
                and root.scope != "read_write"
            )
            or (lease.verb == "device.command.run" and not root.command_enabled)
            or _approval_run_cancelled(
                self, lease.tenant_id, lease.approval_id
            )
            or lease.status != "issued"
            or lease.expires_at <= now
            or lease.expires_at > now + timedelta(seconds=120)
            or (lease.tenant_id, lease.id) in leases or duplicate_approval
        ):
            return False
        leases[(lease.tenant_id, lease.id)] = _copy_lease(lease)
        return True

    async def get_device_lease(self, tenant_id, device_id, lease_id):
        _, _, _, leases = _tables(self)
        row = leases.get((tenant_id, lease_id))
        return _copy_lease(row) if row and row.device_id == device_id else None

    async def list_pending_device_leases(
        self, tenant_id, device_id, limit=50
    ):
        _, devices, roots, leases = _tables(self)
        now = utcnow()
        device = devices.get((tenant_id, device_id))
        rows = [
            _copy_lease(row) for (tenant, _), row in leases.items()
            if tenant == tenant_id and row.device_id == device_id
            and row.status == "issued" and row.expires_at >= now
            and device is not None and device.revoked_at is None
            and (root := roots.get((tenant_id, row.root_id))) is not None
            and root.revoked_at is None
            and not _approval_run_cancelled(
                self, tenant_id, row.approval_id
            )
        ]
        return sorted(rows, key=lambda row: (row.issued_at, row.id))[
            : max(1, min(int(limit), 50))
        ]

    async def list_device_leases_for_owner(
        self, tenant_id, owner_id, device_id, limit=50
    ):
        _, devices, _, leases = _tables(self)
        device = devices.get((tenant_id, device_id))
        if device is None or device.owner_id != owner_id:
            return None
        rows = [
            _copy_lease(row) for (tenant, _), row in leases.items()
            if tenant == tenant_id
            and row.device_id == device_id
            and row.owner_id == owner_id
        ]
        return sorted(
            rows, key=lambda row: (row.issued_at, row.id), reverse=True
        )[: max(1, min(int(limit), 50))]

    async def claim_device_lease(
        self, tenant_id, device_id, lease_id, signature,
        claim_token_hash, claim_expires_at,
    ):
        _, devices, roots, leases = _tables(self)
        row = leases.get((tenant_id, lease_id))
        device = devices.get((tenant_id, device_id))
        root = roots.get((tenant_id, row.root_id)) if row is not None else None
        now = utcnow()
        if (
            row is None or row.device_id != device_id or row.status != "issued"
            or device is None or device.revoked_at is not None
            or root is None or root.revoked_at is not None
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

    async def settle_device_lease(
        self, tenant_id, device_id, lease_id, claim_token_hash, status, receipt
    ):
        _, _, _, leases = _tables(self)
        row = leases.get((tenant_id, lease_id))
        now = utcnow()
        if (
            row is None or row.device_id != device_id or row.status != "claimed"
            or status not in {"completed", "failed"}
            or row.claim_token_hash is None or row.claim_expires_at is None
            or row.claim_expires_at < now
            or not secrets.compare_digest(row.claim_token_hash, claim_token_hash)
        ):
            return False
        row.status = status
        row.receipt = copy.deepcopy(receipt)
        row.settled_at = now
        row.claim_token_hash = None
        return True


def _copy_lease(lease):
    return replace(
        lease,
        action=copy.deepcopy(lease.action),
        receipt=copy.deepcopy(lease.receipt),
    )


def _approval_run_cancelled(store, tenant_id, approval_id):
    approval = getattr(store, "_hitl", {}).get((tenant_id, approval_id))
    return bool(
        approval is not None
        and approval.run_id
        and (tenant_id, approval.run_id) in getattr(store, "_cancels", {})
    )


def _tables(store):
    values = []
    for name in (
        "_device_enrollments", "_devices", "_device_roots", "_device_leases"
    ):
        value = getattr(store, name, None)
        if value is None:
            value = {}
            setattr(store, name, value)
        values.append(value)
    return tuple(values)
