"""Authenticated Worker transport for camera bindings and semantic leases."""

from __future__ import annotations

import json
import re
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.camera_leases import CameraBinding
from boltrig.models import utcnow

from .device_crypto import token_digest
from .device_route_support import CLAIM_TTL, audit_device, authenticate_device, signer_for

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_CAMERA_ID = re.compile(r"^camera_[0-9A-Fa-f]{32}$")
_STATES = frozenset({"unknown", "advertised", "readable", "writable", "proven", "unsupported", "invalid_descriptor"})
_CONNECTIONS = frozenset({"connected", "disconnected", "permission_required", "unknown"})
_RECEIPT_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def _error(reason: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": reason}, status_code=status)


def _text(body: dict, key: str, maximum: int, *, required: bool = True) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum or any(ch in "\r\n\x00" for ch in value):
        raise ValueError(f"invalid_{key}")
    return value


def _binding_from_body(device, body: dict) -> CameraBinding:
    camera_id = _text(body, "camera_id", 39)
    if camera_id is None or _CAMERA_ID.fullmatch(camera_id) is None:
        raise ValueError("invalid_camera_id")
    fingerprint = _text(body, "descriptor_fingerprint", 64)
    if fingerprint is None or _FINGERPRINT.fullmatch(fingerprint) is None:
        raise ValueError("invalid_descriptor_fingerprint")
    connection_state = _text(body, "connection_state", 32)
    get_state = _text(body, "ptz_get_state", 32)
    set_state = _text(body, "ptz_set_state", 32)
    if connection_state not in _CONNECTIONS:
        raise ValueError("invalid_connection_state")
    if get_state not in _STATES or set_state not in _STATES:
        raise ValueError("invalid_ptz_state")
    label = _text(body, "label", 256, required=False) or ""
    manufacturer = _text(body, "manufacturer", 256, required=False)
    product = _text(body, "product", 256, required=False)
    transport = _text(body, "transport", 64, required=False) or "uvc_libusb"
    capabilities = body.get("capabilities", {})
    evidence = body.get("evidence", [])
    if not isinstance(capabilities, dict) or not isinstance(evidence, list):
        raise ValueError("invalid_camera_evidence")
    if set_state == "proven" and "bounded_uvc_set_readback_frame_change_and_exact_restoration" not in evidence:
        raise ValueError("camera_physical_proof_evidence_required")
    try:
        encoded = json.dumps(
            {"capabilities": capabilities, "evidence": evidence},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_camera_evidence") from exc
    if len(encoded) > 64_000 or len(evidence) > 64:
        raise ValueError("camera_evidence_too_large")
    return CameraBinding(
        tenant_id=device.tenant_id,
        device_id=device.id,
        camera_id=camera_id,
        descriptor_fingerprint=fingerprint,
        owner_id=device.owner_id,
        connection_state=connection_state,
        ptz_get_state=get_state,
        ptz_set_state=set_state,
        label=label,
        manufacturer=manufacturer,
        product=product,
        transport=transport,
        capabilities=capabilities,
        evidence=evidence,
        updated_at=utcnow(),
    )


def binding_view(binding) -> dict:
    return {
        "tenant_id": binding.tenant_id,
        "device_id": binding.device_id,
        "camera_id": binding.camera_id,
        "descriptor_fingerprint": binding.descriptor_fingerprint,
        "label": binding.label,
        "manufacturer": binding.manufacturer,
        "product": binding.product,
        "transport": binding.transport,
        "connection_state": binding.connection_state,
        "ptz_get_state": binding.ptz_get_state,
        "ptz_set_state": binding.ptz_set_state,
        "capabilities": binding.capabilities,
        "evidence": binding.evidence,
        "updated_at": binding.updated_at.isoformat() if binding.updated_at else None,
    }


def lease_view(lease) -> dict:
    return {
        **lease.canonical_payload(),
        "signature": lease.signature,
        "status": lease.status,
    }


def owner_lease_view(lease) -> dict:
    status = lease.status
    if status == "issued" and lease.expires_at < utcnow():
        status = "expired"
    if status == "claimed" and lease.claim_expires_at is not None and lease.claim_expires_at < utcnow():
        status = "expired"
    receipt = None
    if status in {"completed", "failed"} and isinstance(lease.receipt, dict):
        code = lease.receipt.get("code")
        if isinstance(code, str) and _RECEIPT_CODE.fullmatch(code):
            receipt = {"code": code}
    return {
        "id": lease.id,
        "device_id": lease.device_id,
        "camera_id": lease.camera_id,
        "verb": lease.verb,
        "status": status,
        "issued_at": lease.issued_at.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
        "settled_at": lease.settled_at.isoformat() if lease.settled_at else None,
        "receipt": receipt,
    }


async def list_owner_bindings(device_id: str, kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    rows = await kernel.store.list_camera_bindings(principal.tenant_id, principal.subject, device_id)
    return {"bindings": [binding_view(row) for row in rows]}


async def list_owner_leases(device_id: str, kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    rows = await kernel.store.list_camera_leases_for_owner(
        principal.tenant_id, principal.subject, device_id
    )
    if rows is None:
        return _error("device_not_found", 404)
    return {"leases": [owner_lease_view(row) for row in rows]}


async def publish_binding(device_id: str, body: dict, request: Request, kernel):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    try:
        binding = _binding_from_body(device, body)
    except ValueError as exc:
        return _error(str(exc))
    if not await kernel.store.upsert_camera_binding(binding):
        return _error("camera_binding_unavailable", 409)
    await audit_device(
        kernel, device.tenant_id, f"device:{device_id}",
        "camera.binding.publish", device_id,
        {"camera_id": binding.camera_id, "transport": binding.transport},
    )
    return {"binding": binding_view(binding)}


async def list_bindings(device_id: str, request: Request, kernel):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    rows = await kernel.store.list_camera_bindings(device.tenant_id, device.owner_id, device_id)
    return {"bindings": [binding_view(row) for row in rows]}


async def pending_leases(device_id: str, request: Request, kernel):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    rows = await kernel.store.list_pending_camera_leases(device.tenant_id, device_id)
    return {"leases": [lease_view(row) for row in rows]}


async def claim_lease(device_id: str, lease_id: str, body: dict, request: Request, kernel):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    signature = body.get("signature")
    if not isinstance(signature, str):
        return _error("signature_required")
    lease = await kernel.store.get_camera_lease(device.tenant_id, device_id, lease_id)
    signer = signer_for(request)
    if lease is None or signer is None or signature != lease.signature or not signer.verify(lease):
        return _error("invalid_camera_lease_signature", 403)
    claim_token = secrets.token_urlsafe(32)
    claimed = await kernel.store.claim_camera_lease(
        device.tenant_id, device_id, lease_id, signature,
        token_digest(claim_token), utcnow() + CLAIM_TTL,
    )
    if claimed is None:
        return _error("camera_lease_unavailable", 409)
    await audit_device(
        kernel, device.tenant_id, f"device:{device_id}",
        "camera.lease.claim", device_id,
        {"lease_id": lease_id, "camera_id": claimed.camera_id, "verb": claimed.verb},
    )
    return {
        "lease": lease_view(claimed),
        "claim_token": claim_token,
        "claim_expires_at": claimed.claim_expires_at.isoformat(),
    }


async def settle_lease(device_id: str, lease_id: str, body: dict, request: Request, kernel):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    claim_token = body.get("claim_token")
    status = body.get("status")
    if not isinstance(claim_token, str) or status not in {"completed", "failed"}:
        return _error("claim_token_and_terminal_status_required")
    receipt = body.get("receipt", {})
    if not isinstance(receipt, dict):
        return _error("receipt_must_be_object")
    try:
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return _error("invalid_receipt")
    if len(encoded) > 32_000:
        return _error("receipt_too_large")
    if not await kernel.store.settle_camera_lease(
        device.tenant_id, device_id, lease_id, token_digest(claim_token), status, receipt
    ):
        return _error("camera_claim_unavailable", 409)
    await audit_device(
        kernel, device.tenant_id, f"device:{device_id}",
        "camera.lease.receipt", device_id,
        {"lease_id": lease_id, "status": status},
    )
    return {"status": "ok"}


def _device_endpoint(handler, kernel_dep):
    async def endpoint(device_id: str, request: Request, k=kernel_dep):
        return await handler(device_id, request, k)
    return endpoint


def _binding_endpoint(kernel_dep):
    async def endpoint(device_id: str, body: dict, request: Request, k=kernel_dep):
        return await publish_binding(device_id, body, request, k)
    return endpoint


def _lease_endpoint(handler, kernel_dep):
    async def endpoint(device_id: str, lease_id: str, body: dict, request: Request, k=kernel_dep):
        return await handler(device_id, lease_id, body, request, k)
    return endpoint


def register_camera_agent_routes(app, *, get_kernel) -> None:
    from fastapi import Depends

    kernel = Depends(get_kernel)
    app.add_api_route(
        "/v1/device-agent/{device_id}/camera-bindings",
        _binding_endpoint(kernel), methods=["POST"], name="publish_camera_binding",
    )
    app.add_api_route(
        "/v1/device-agent/{device_id}/camera-bindings",
        _device_endpoint(list_bindings, kernel), methods=["GET"], name="list_camera_bindings",
    )
    app.add_api_route(
        "/v1/device-agent/{device_id}/camera-leases",
        _device_endpoint(pending_leases, kernel), methods=["GET"], name="pending_camera_leases",
    )
    for suffix, handler, name in (("claim", claim_lease, "claim_camera_lease"), ("receipt", settle_lease, "settle_camera_lease")):
        app.add_api_route(
            f"/v1/device-agent/{{device_id}}/camera-leases/{{lease_id}}/{suffix}",
            _lease_endpoint(handler, kernel), methods=["POST"], name=name,
        )


__all__ = [
    "binding_view", "lease_view", "owner_lease_view", "list_owner_bindings",
    "list_owner_leases", "register_camera_agent_routes",
]
