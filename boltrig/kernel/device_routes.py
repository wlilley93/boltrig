"""Authenticated user routes for decision-0021 desktop devices."""

from __future__ import annotations

import os
import uuid

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.models import utcnow
from boltrig.models.devices import (
    DEVICE_ROOT_SCOPES,
    DeviceEnrollment,
    DeviceRoot,
)

from .device_agent_routes import register_device_agent_routes
from .camera_agent_routes import (
    list_owner_bindings as list_owner_camera_bindings,
    list_owner_leases as list_owner_camera_leases,
)
from .device_crypto import mint_scoped_token, token_digest
from .device_route_support import (
    ENROLLMENT_TTL,
    audit_device,
    device_view,
    owner_lease_view,
    signer_for,
)


def _error(reason: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": reason}, status_code=status)


# The reasons a validation failure in this module may state to a caller. Telling
# them WHICH field was wrong is deliberate and is the same principle as the
# caller-facing schema hints: a bare "invalid" makes a client retry the identical
# request. What must not reach them is an arbitrary exception message.
#
# Every `raise ValueError` below uses one of these, so today `str(exc)` would be
# safe - but that is a property of five call sites agreeing, which is the kind of
# claim this repository has learned not to rest on. `_validation_reason` makes it
# a mechanism: a token nobody registered becomes the generic answer instead of
# being forwarded, so adding a `raise ValueError(f"bad {value}")` here leaks
# nothing and shows up as an unhelpful message rather than as a disclosure.
_VALIDATION_REASONS = frozenset({
    "invalid_label",
    "invalid_root_scope",
    "invalid_command_enabled",
    "invalid_git_enabled",
})


def _validation_reason(exc: Exception) -> str:
    reason = str(exc)
    return reason if reason in _VALIDATION_REASONS else "invalid_request"


def _label(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_label")
    clean = value.strip()
    if not clean or len(clean) > 100 or any(not ch.isprintable() for ch in clean):
        raise ValueError("invalid_label")
    return clean


async def start_enrollment(body: dict, request: Request, kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    signer = signer_for(request)
    if signer is None:
        return _error("device_leases_unavailable", 503)
    try:
        label = _label(body.get("label"))
    except ValueError as exc:
        return _error(_validation_reason(exc))
    enrollment_id = uuid.uuid4().hex
    code = mint_scoped_token(
        "device_enrollment", principal.tenant_id, enrollment_id
    )
    now = utcnow()
    enrollment = DeviceEnrollment(
        id=enrollment_id, tenant_id=principal.tenant_id,
        owner_id=principal.subject, label=label,
        authorization_code_hash=token_digest(code),
        expires_at=now + ENROLLMENT_TTL, created_at=now,
    )
    if not await kernel.store.create_device_enrollment(enrollment):
        return _error("enrollment_conflict", 409)
    await audit_device(
        kernel, principal.tenant_id, principal.subject,
        "device.enrollment.start", enrollment_id, {},
    )
    return {
        "authorization_code": code,
        "expires_at": enrollment.expires_at.isoformat(),
        "verification_uri": os.environ.get(
            "BOLTRIG_DEVICE_VERIFICATION_URI", "/#/settings"
        ),
        "lease_verifier": signer.verifier_view(),
    }


async def list_devices(kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    rows = await kernel.store.list_devices(
        principal.tenant_id, principal.subject
    )
    return {
        "devices": [
            device_view(
                device,
                await kernel.store.list_device_roots(
                    principal.tenant_id, device.id
                ),
            )
            for device in rows
        ]
    }


async def list_owner_leases(device_id: str, kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    rows = await kernel.store.list_device_leases_for_owner(
        principal.tenant_id, principal.subject, device_id
    )
    if rows is None:
        return _error("device_not_found", 404)
    return {"leases": [owner_lease_view(row) for row in rows]}


async def create_root(device_id: str, body: dict, kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    try:
        label = _label(body.get("label"))
        scope = str(body.get("scope") or "")
        if scope not in DEVICE_ROOT_SCOPES:
            raise ValueError("invalid_root_scope")
        if not isinstance(body.get("command_enabled", False), bool):
            raise ValueError("invalid_command_enabled")
        if not isinstance(body.get("git_enabled", False), bool):
            raise ValueError("invalid_git_enabled")
    except ValueError as exc:
        return _error(_validation_reason(exc))
    root = DeviceRoot(
        id=uuid.uuid4().hex, tenant_id=principal.tenant_id,
        device_id=device_id, label=label, scope=scope,
        command_enabled=body.get("command_enabled", False),
        git_enabled=body.get("git_enabled", False),
    )
    if not await kernel.store.create_device_root(root, principal.subject):
        return _error("device_not_found", 404)
    await audit_device(
        kernel, principal.tenant_id, principal.subject,
        "device.root.register", device_id,
        {"root_id": root.id, "scope": scope,
         "command_enabled": root.command_enabled},
    )
    return {"root": device_view(
        await kernel.store.get_device(principal.tenant_id, device_id), [root]
    )["roots"][0]}


async def revoke_root(
    device_id: str, root_id: str, kernel, principal
):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    if not await kernel.store.revoke_device_root(
        principal.tenant_id, device_id, root_id, principal.subject
    ):
        return _error("root_not_found", 404)
    await audit_device(
        kernel, principal.tenant_id, principal.subject,
        "device.root.revoke", device_id, {"root_id": root_id},
    )
    return {"status": "ok"}


async def revoke_device(device_id: str, kernel, principal):
    if principal.actor_tier != "human":
        return _error("human_required", 403)
    if not await kernel.store.revoke_device(
        principal.tenant_id, device_id, principal.subject
    ):
        return _error("device_not_found", 404)
    await audit_device(
        kernel, principal.tenant_id, principal.subject,
        "device.revoke", device_id, {},
    )
    return {"status": "ok"}


def _body_endpoint(handler, principal_dep, kernel_dep):
    async def endpoint(body: dict, request: Request, k=kernel_dep, p=principal_dep):
        return await handler(body, request, k, p)
    return endpoint


def _list_endpoint(principal_dep, kernel_dep):
    async def endpoint(k=kernel_dep, p=principal_dep):
        return await list_devices(k, p)
    return endpoint


def _root_endpoint(principal_dep, kernel_dep):
    async def endpoint(device_id: str, body: dict, k=kernel_dep, p=principal_dep):
        return await create_root(device_id, body, k, p)
    return endpoint


def _revoke_root_endpoint(principal_dep, kernel_dep):
    async def endpoint(
        device_id: str, root_id: str, k=kernel_dep, p=principal_dep
    ):
        return await revoke_root(device_id, root_id, k, p)
    return endpoint


def _device_endpoint(handler, principal_dep, kernel_dep):
    async def endpoint(device_id: str, k=kernel_dep, p=principal_dep):
        return await handler(device_id, k, p)
    return endpoint


def register_device_routes(app, *, principal_dep, get_kernel) -> None:
    principal, kernel = Depends(principal_dep), Depends(get_kernel)
    app.add_api_route(
        "/v1/devices/enrollment/start",
        _body_endpoint(start_enrollment, principal, kernel),
        methods=["POST"], name="start_device_enrollment",
    )
    app.add_api_route(
        "/v1/devices", _list_endpoint(principal, kernel),
        methods=["GET"], name="list_devices",
    )
    app.add_api_route(
        "/v1/devices/{device_id}/leases",
        _device_endpoint(list_owner_leases, principal, kernel),
        methods=["GET"], name="list_owner_device_leases",
    )
    app.add_api_route(
        "/v1/devices/{device_id}/camera-bindings",
        _device_endpoint(list_owner_camera_bindings, principal, kernel),
        methods=["GET"], name="list_owner_camera_bindings",
    )
    app.add_api_route(
        "/v1/devices/{device_id}/camera-leases",
        _device_endpoint(list_owner_camera_leases, principal, kernel),
        methods=["GET"], name="list_owner_camera_leases",
    )
    app.add_api_route(
        "/v1/devices/{device_id}/roots", _root_endpoint(principal, kernel),
        methods=["POST"], name="create_device_root",
    )
    app.add_api_route(
        "/v1/devices/{device_id}/roots/{root_id}",
        _revoke_root_endpoint(principal, kernel),
        methods=["DELETE"], name="revoke_device_root",
    )
    app.add_api_route(
        "/v1/devices/{device_id}",
        _device_endpoint(revoke_device, principal, kernel),
        methods=["DELETE"], name="revoke_device",
    )
    register_device_agent_routes(app, get_kernel=get_kernel)
