"""Device-session authenticated enrollment, lease claim and receipt routes."""

from __future__ import annotations

import json
import secrets
import uuid

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.models import utcnow
from boltrig.models.devices import EnrolledDevice
from boltrig.store.postgres import set_current_tenant

from .device_crypto import parse_scoped_token, token_digest
from .device_route_support import (
    CLAIM_TTL,
    SESSION_TTL,
    audit_device,
    authenticate_device,
    bearer,
    device_view,
    lease_view,
    mint_device_session,
    public_key_fingerprint,
    signer_for,
)
from .camera_agent_routes import register_camera_agent_routes


def _error(reason: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": reason}, status_code=status)


async def complete_enrollment(body: dict, request: Request, kernel):
    signer = signer_for(request)
    if signer is None:
        return _error("device_leases_unavailable", 503)
    code = body.get("authorization_code")
    public_key = body.get("device_public_key")
    if not isinstance(code, str) or not isinstance(public_key, str):
        return _error("authorization_code_and_device_public_key_required")
    try:
        tenant_id, enrollment_id = parse_scoped_token(code, "device_enrollment")
        fingerprint = public_key_fingerprint(public_key)
    except ValueError:
        return _error("invalid_or_expired_enrollment", 401)
    device_id = uuid.uuid4().hex
    session_token, session_hash = mint_device_session(tenant_id, device_id)
    now = utcnow()
    device = EnrolledDevice(
        id=device_id, tenant_id=tenant_id, owner_id="", label="Enrolled device",
        public_key=public_key, public_key_fingerprint=fingerprint,
        lease_verify_key_id=signer.key_id, session_token_hash=session_hash,
        session_expires_at=now + SESSION_TTL, created_at=now, updated_at=now,
    )
    set_current_tenant(tenant_id)
    try:
        completed = await kernel.store.complete_device_enrollment(
            tenant_id, enrollment_id, token_digest(code), device
        )
    finally:
        set_current_tenant(None)
    if completed is None:
        return _error("invalid_or_expired_enrollment", 401)
    await audit_device(
        kernel, tenant_id, f"device:{device_id}", "device.enrollment.complete",
        device_id, {},
    )
    return {
        "status": "ok", "device": device_view(completed, []),
        "session_token": session_token,
        "session_expires_at": device.session_expires_at.isoformat(),
        "lease_verifier": signer.verifier_view(),
    }


async def pending_leases(device_id: str, request: Request, kernel):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    rows = await kernel.store.list_pending_device_leases(
        device.tenant_id, device_id
    )
    return {"leases": [lease_view(row) for row in rows]}


async def claim_lease(
    device_id: str, lease_id: str, body: dict, request: Request, kernel
):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    signature = body.get("signature")
    if not isinstance(signature, str):
        return _error("signature_required")
    lease = await kernel.store.get_device_lease(
        device.tenant_id, device_id, lease_id
    )
    signer = signer_for(request)
    if (
        lease is None or signer is None or signature != lease.signature
        or not signer.verify(lease)
    ):
        return _error("invalid_lease_signature", 403)
    claim_token = secrets.token_urlsafe(32)
    claimed = await kernel.store.claim_device_lease(
        device.tenant_id, device_id, lease_id, signature,
        token_digest(claim_token), utcnow() + CLAIM_TTL,
    )
    if claimed is None:
        return _error("lease_unavailable", 409)
    await audit_device(
        kernel,
        device.tenant_id,
        f"device:{device_id}",
        "device.lease.claim",
        device_id,
        {"lease_id": lease_id, "verb": claimed.verb},
    )
    return {
        "lease": lease_view(claimed), "claim_token": claim_token,
        "claim_expires_at": claimed.claim_expires_at.isoformat(),
    }


async def settle_lease(
    device_id: str, lease_id: str, body: dict, request: Request, kernel
):
    device = await authenticate_device(request, kernel, device_id)
    if device is None:
        return _error("invalid_device_session", 401)
    claim_token = body.get("claim_token")
    status = body.get("status")
    if not isinstance(claim_token, str) or status not in {"completed", "failed"}:
        return _error("claim_token_and_terminal_status_required")
    raw_receipt = body.get("receipt", {})
    if not isinstance(raw_receipt, dict):
        return _error("receipt_must_be_object")
    try:
        receipt_bytes = json.dumps(
            raw_receipt,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return _error("invalid_receipt")
    if len(receipt_bytes) > 32_000:
        return _error("receipt_too_large")
    receipt = raw_receipt
    if not await kernel.store.settle_device_lease(
        device.tenant_id, device_id, lease_id, token_digest(claim_token),
        status, receipt,
    ):
        return _error("claim_unavailable", 409)
    await audit_device(
        kernel, device.tenant_id, f"device:{device_id}",
        "device.lease.receipt", device_id,
        {"lease_id": lease_id, "status": status},
    )
    return {"status": "ok"}


async def rotate_session(device_id: str, request: Request, kernel):
    token = bearer(request)
    device = await authenticate_device(request, kernel, device_id)
    if device is None or token is None:
        return _error("invalid_device_session", 401)
    new_token, new_hash = mint_device_session(device.tenant_id, device_id)
    expires_at = utcnow() + SESSION_TTL
    if not await kernel.store.rotate_device_session(
        device.tenant_id, device_id, token_digest(token), new_hash, expires_at
    ):
        return _error("session_rotation_conflict", 409)
    return {
        "session_token": new_token,
        "session_expires_at": expires_at.isoformat(),
    }


def _complete_endpoint(kernel_dep):
    async def endpoint(body: dict, request: Request, k=kernel_dep):
        return await complete_enrollment(body, request, k)
    return endpoint


def _device_endpoint(handler, kernel_dep):
    async def endpoint(device_id: str, request: Request, k=kernel_dep):
        return await handler(device_id, request, k)
    return endpoint


def _lease_endpoint(handler, kernel_dep):
    async def endpoint(
        device_id: str, lease_id: str, body: dict, request: Request, k=kernel_dep
    ):
        return await handler(device_id, lease_id, body, request, k)
    return endpoint


def register_device_agent_routes(app, *, get_kernel) -> None:
    kernel = Depends(get_kernel)
    app.add_api_route(
        "/v1/device-agent/enrollment/complete", _complete_endpoint(kernel),
        methods=["POST"], name="complete_device_enrollment",
    )
    app.add_api_route(
        "/v1/device-agent/{device_id}/leases",
        _device_endpoint(pending_leases, kernel), methods=["GET"],
        name="pending_device_leases",
    )
    for suffix, handler, name in (
        ("claim", claim_lease, "claim_device_lease"),
        ("receipt", settle_lease, "settle_device_lease"),
    ):
        app.add_api_route(
            f"/v1/device-agent/{{device_id}}/leases/{{lease_id}}/{suffix}",
            _lease_endpoint(handler, kernel), methods=["POST"], name=name,
        )
    app.add_api_route(
        "/v1/device-agent/{device_id}/session/rotate",
        _device_endpoint(rotate_session, kernel), methods=["POST"],
        name="rotate_device_session",
    )
    register_camera_agent_routes(app, get_kernel=get_kernel)
