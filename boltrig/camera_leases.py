"""Camera-specific signed lease materialization.

This module is intentionally separate from :mod:`boltrig.device_leases`.
There is no filesystem root, argv, shell primitive, HID report, or implicit
fallback in the camera lease contract.
"""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from boltrig.models import HITLStatus, HITLType, utcnow
from boltrig.models.camera_actions import canonical_camera_action

CAMERA_LEASE_TTL = timedelta(seconds=120)
_APPROVING = frozenset({"approve", "approved", "yes", "allow"})


@dataclass(frozen=True)
class CameraBinding:
    device_id: str
    camera_id: str
    descriptor_fingerprint: str
    owner_id: str
    connection_state: str
    ptz_get_state: str
    ptz_set_state: str
    label: str = ""
    manufacturer: str | None = None
    product: str | None = None
    transport: str = "uvc_libusb"
    capabilities: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    updated_at: Any = None
    tenant_id: str = ""


@dataclass
class CameraLease:
    id: str
    tenant_id: str
    device_id: str
    camera_id: str
    owner_id: str
    verb: str
    action: dict[str, Any]
    action_digest: str
    approval_id: str
    issued_at: Any
    expires_at: Any
    signature: str = ""
    signing_key_id: str = ""
    status: str = "issued"
    claim_token_hash: str | None = None
    claim_expires_at: Any = None
    claimed_at: Any = None
    settled_at: Any = None
    receipt: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.id,
            "tenant_id": self.tenant_id,
            "device_id": self.device_id,
            "camera_id": self.camera_id,
            "owner_id": self.owner_id,
            "verb": self.verb,
            "action": self.action,
            "action_digest": self.action_digest,
            "approval_id": self.approval_id,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "signing_key_id": self.signing_key_id,
        }

    def canonical_bytes(self) -> bytes:
        import json

        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")


class CameraLeaseStore(Protocol):
    async def get_camera_binding(
        self, tenant_id: str, device_id: str, camera_id: str
    ) -> CameraBinding | None: ...

    async def create_camera_lease(self, lease: CameraLease) -> bool: ...

    async def get_hitl_request(self, tenant_id: str, request_id: str) -> Any: ...

    async def get_hitl_response(self, tenant_id: str, request_id: str) -> Any: ...


class CameraLeaseIssueError(Exception):
    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class CameraLeaseSigner(Protocol):
    key_id: str

    def sign(self, lease: CameraLease) -> CameraLease: ...


class CameraLeaseIssuer:
    """Materialize one exact, approval-bound PTZ lease for one camera binding."""

    def __init__(self, store: CameraLeaseStore, signer: CameraLeaseSigner | None) -> None:
        self._store = store
        self._signer = signer

    async def resource_context(
        self,
        tenant_id: str,
        owner_id: str,
        device_id: str,
        camera_id: str,
        verb: str,
        raw_action: object,
        *,
        run_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if self._signer is None:
            raise CameraLeaseIssueError("camera_leases_unavailable", 503)
        try:
            action, action_digest = canonical_camera_action(
                device_id, camera_id, verb, raw_action
            )
        except ValueError as exc:
            raise CameraLeaseIssueError(str(exc), 400) from exc
        binding = await self._store.get_camera_binding(tenant_id, device_id, camera_id)
        if (
            binding is None
            or binding.owner_id != owner_id
            or binding.device_id != device_id
            or binding.camera_id != camera_id
            or binding.connection_state != "connected"
            or binding.ptz_get_state not in {"readable", "proven"}
            or (verb == "camera.ptz.set" and binding.ptz_set_state != "proven")
            or action["descriptor_fingerprint"] != binding.descriptor_fingerprint
        ):
            raise CameraLeaseIssueError("camera_binding_not_proven", 409)
        is_cancelled = getattr(self._store, "is_run_cancel_requested", None)
        if callable(is_cancelled):
            for run_id in dict.fromkeys(value for value in run_ids if value):
                if await is_cancelled(tenant_id, run_id):
                    raise CameraLeaseIssueError("run_cancelled", 409)
        return {
            "device_id": device_id,
            "camera_id": camera_id,
            "descriptor_fingerprint": binding.descriptor_fingerprint,
            "verb": verb,
            "action_digest": action_digest,
        }

    async def materialize(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        device_id: str,
        camera_id: str,
        verb: str,
        raw_action: object,
        approval_id: str,
        approved_by: str,
        run_ids: tuple[str, ...] = (),
    ) -> CameraLease:
        signer = self._signer
        if signer is None:
            raise CameraLeaseIssueError("camera_leases_unavailable", 503)
        await self.resource_context(
            tenant_id, owner_id, device_id, camera_id, verb, raw_action,
            run_ids=run_ids,
        )
        action, action_digest = canonical_camera_action(
            device_id, camera_id, verb, raw_action
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
            or owner_id not in {request.requested_by, request.requested_on_behalf_of}
            or response.respondent in {request.requested_by, request.requested_on_behalf_of}
            or not hmac.compare_digest(response.respondent, approved_by)
            or response.decision.strip().lower() not in _APPROVING
            or (request.timeout_at is not None and request.timeout_at <= utcnow())
        ):
            raise CameraLeaseIssueError("consumed_exact_action_approval_required", 403)
        is_cancelled = getattr(self._store, "is_run_cancel_requested", None)
        if callable(is_cancelled) and request.run_id:
            if await is_cancelled(tenant_id, request.run_id):
                raise CameraLeaseIssueError("run_cancelled", 409)
        now = utcnow()
        lease = signer.sign(
            CameraLease(
                id=uuid.uuid4().hex,
                tenant_id=tenant_id,
                device_id=device_id,
                camera_id=camera_id,
                owner_id=owner_id,
                verb=verb,
                action=action,
                action_digest=action_digest,
                approval_id=approval_id,
                issued_at=now,
                expires_at=now + CAMERA_LEASE_TTL,
            )
        )
        if not await self._store.create_camera_lease(lease):
            raise CameraLeaseIssueError("camera_lease_not_materialized", 409)
        return lease


__all__ = [
    "CAMERA_LEASE_TTL",
    "CameraBinding",
    "CameraLease",
    "CameraLeaseIssueError",
    "CameraLeaseIssuer",
]
