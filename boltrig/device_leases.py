"""Shared exact-action device lease materialization over the stable store seam."""

from __future__ import annotations

import hmac
import uuid
from datetime import timedelta
from typing import Any, Protocol

from boltrig.models import HITLStatus, HITLType, utcnow
from boltrig.models.device_actions import canonical_device_action
from boltrig.models.devices import DeviceLease

DEVICE_LEASE_TTL = timedelta(seconds=120)
_APPROVING = frozenset({"approve", "approved", "yes", "allow"})


class DeviceLeaseIssueError(Exception):
    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class LeaseSigner(Protocol):
    key_id: str

    def sign(self, lease: DeviceLease) -> DeviceLease: ...


class DeviceLeaseIssuer:
    """Validate mutable device state, then atomically persist one signed lease."""

    def __init__(self, store: Any, signer: LeaseSigner | None) -> None:
        self._store = store
        self._signer = signer

    async def resource_context(
        self,
        tenant_id: str,
        owner_id: str,
        device_id: str,
        root_id: str,
        verb: str,
        raw_action: object,
        *,
        run_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Return only public, authority-bearing device state for HITL binding."""
        if self._signer is None:
            raise DeviceLeaseIssueError("device_leases_unavailable", 503)
        try:
            canonical_device_action(device_id, root_id, verb, raw_action)
        except ValueError as exc:
            raise DeviceLeaseIssueError(str(exc), 400) from exc
        device = await self._store.get_device(tenant_id, device_id)
        roots = await self._store.list_device_roots(tenant_id, device_id)
        root = next((item for item in roots if item.id == root_id), None)
        if (
            device is None
            or device.owner_id != owner_id
            or device.revoked_at is not None
            or root is None
        ):
            raise DeviceLeaseIssueError("device_or_root_not_found", 404)
        if device.lease_verify_key_id != self._signer.key_id:
            raise DeviceLeaseIssueError("device_verifier_stale", 409)
        if verb == "device.file.write" and root.scope != "read_write":
            raise DeviceLeaseIssueError("root_is_read_only", 403)
        if verb == "device.command.run" and not root.command_enabled:
            raise DeviceLeaseIssueError("command_disabled", 403)
        for run_id in dict.fromkeys(value for value in run_ids if value):
            if await self._store.is_run_cancel_requested(tenant_id, run_id):
                raise DeviceLeaseIssueError("run_cancelled", 409)
        return {
            "device_id": device.id,
            "root_id": root.id,
            "root_scope": root.scope,
            "command_enabled": root.command_enabled,
            "lease_verify_key_id": device.lease_verify_key_id,
        }

    async def materialize(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        device_id: str,
        root_id: str,
        verb: str,
        raw_action: object,
        approval_id: str,
        approved_by: str,
        run_ids: tuple[str, ...] = (),
    ) -> DeviceLease:
        """Create the sole lease admitted by one consumed, independent approval."""
        signer = self._signer
        if signer is None:
            raise DeviceLeaseIssueError("device_leases_unavailable", 503)
        await self.resource_context(
            tenant_id,
            owner_id,
            device_id,
            root_id,
            verb,
            raw_action,
            run_ids=run_ids,
        )
        action, action_digest = canonical_device_action(
            device_id, root_id, verb, raw_action
        )
        request = await self._store.get_hitl_request(tenant_id, approval_id)
        response = await self._store.get_hitl_response(tenant_id, approval_id)
        if (
            request is None
            or response is None
            or request.status != HITLStatus.CONSUMED
            or request.type != HITLType.APPROVAL
            or request.verb != verb
            or request.action_digest is None
            or not hmac.compare_digest(request.action_digest, action_digest)
            or owner_id not in {
                request.requested_by,
                request.requested_on_behalf_of,
            }
            or response.respondent in {
                request.requested_by,
                request.requested_on_behalf_of,
            }
            or not hmac.compare_digest(response.respondent, approved_by)
            or response.decision.strip().lower() not in _APPROVING
            or (request.timeout_at is not None and request.timeout_at <= utcnow())
        ):
            raise DeviceLeaseIssueError(
                "consumed_exact_action_approval_required", 403
            )
        if request.run_id and await self._store.is_run_cancel_requested(
            tenant_id, request.run_id
        ):
            raise DeviceLeaseIssueError("run_cancelled", 409)
        now = utcnow()
        lease = signer.sign(
            DeviceLease(
                id=uuid.uuid4().hex,
                tenant_id=tenant_id,
                device_id=device_id,
                root_id=root_id,
                owner_id=owner_id,
                verb=verb,
                action=action,
                action_digest=action_digest,
                approval_id=approval_id,
                issued_at=now,
                expires_at=now + DEVICE_LEASE_TTL,
            )
        )
        if not await self._store.create_device_lease(lease):
            raise DeviceLeaseIssueError("device_lease_not_materialized", 409)
        return lease


__all__ = [
    "DEVICE_LEASE_TTL",
    "DeviceLeaseIssueError",
    "DeviceLeaseIssuer",
]
