"""Governed semantic PTZ leases for enrolled native camera backends."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.camera_leases import CameraLeaseIssueError, CameraLeaseIssuer
from boltrig.models import AdapterFailure, InvocationContext

CAMERA_LEASE_VERBS = ("camera.ptz.get", "camera.ptz.set")
_ID = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9_-]+$"}
_CAMERA_ID = {"type": "string", "pattern": "^camera_[A-Fa-f0-9]{32}$"}
_FINGERPRINT = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ANGLE = {"type": "integer", "minimum": -360000000, "maximum": 360000000}


def _input(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"device_id": _ID, "camera_id": _CAMERA_ID, **properties},
        "required": ["device_id", "camera_id", *required],
        "additionalProperties": False,
    }


def camera_lease_specs() -> list[VerbSpec]:
    common: dict[str, Any] = {
        "noun_id": "camera",
        "consequence": "high",
        "rate_limit": {"per": "minute", "max": 30, "scope": "tenant"},
        "idempotency_mode": "cacheable",
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"const": "leased"},
                "lease_id": _ID,
                "device_id": _ID,
                "camera_id": _CAMERA_ID,
                "verb": {"enum": list(CAMERA_LEASE_VERBS)},
                "expires_at": {"type": "string", "maxLength": 64},
            },
            "required": ["status", "lease_id", "device_id", "camera_id", "verb", "expires_at"],
            "additionalProperties": False,
        },
    }
    return [
        VerbSpec(
            verb_id="camera.ptz.get",
            input_schema=_input({"descriptor_fingerprint": _FINGERPRINT}, ["descriptor_fingerprint"]),
            description="Issue one signed lease for a bounded standard-UVC PTZ readback.",
            **common,
        ),
        VerbSpec(
            verb_id="camera.ptz.set",
            input_schema=_input(
                {"descriptor_fingerprint": _FINGERPRINT, "pan_millidegrees": _ANGLE, "tilt_millidegrees": _ANGLE},
                ["descriptor_fingerprint", "pan_millidegrees", "tilt_millidegrees"],
            ),
            description="Issue one exact, approval-bound signed standard-UVC PTZ lease.",
            **common,
        ),
    ]


def _action(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in {"device_id", "camera_id"}}


def _adapter_error(exc: CameraLeaseIssueError) -> AdapterError:
    kind = {
        403: ErrorClass.UNAUTHORISED,
        404: ErrorClass.NOT_FOUND,
        409: ErrorClass.CONFLICT,
        503: ErrorClass.UNAVAILABLE,
    }.get(exc.status_code, ErrorClass.INVALID)
    return AdapterError(kind, exc.reason)


class CameraLeaseAdapter:
    id = "camera"
    version = "1.1.0"
    runtime = "script"

    def __init__(self, issuer: CameraLeaseIssuer) -> None:
        self._issuer = issuer

    def describe(self) -> list[VerbSpec]:
        return camera_lease_specs()

    async def approval_context(self, verb: str, params: dict[str, Any], context: InvocationContext) -> dict[str, Any]:
        try:
            return await self._issuer.resource_context(
                context.tenant_id,
                context.on_behalf_of or context.actor,
                params["device_id"],
                params["camera_id"],
                verb,
                _action(params),
                run_ids=tuple(
                    value
                    for value in (context.run_id, context.parent_run_id)
                    if value
                ),
            )
        except CameraLeaseIssueError as exc:
            raise AdapterFailure(exc.reason, status_code=exc.status_code, reason=exc.reason) from exc

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del credential
        if verb not in CAMERA_LEASE_VERBS:
            return Result.failure(AdapterError(ErrorClass.INVALID, "unsupported_camera_lease_verb"))
        expected = context.extra.get("approval_resource_context")
        fingerprint = context.extra.get("approval_request_fingerprint")
        approval_id = context.extra.get("approval_request_id")
        approved_by = context.extra.get("approved_by")
        try:
            current = await self.approval_context(verb, params, context)
        except AdapterFailure as exc:
            return Result.failure(_adapter_error(CameraLeaseIssueError(exc.reason, exc.status_code)))
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or expected != current
            or not isinstance(approval_id, str)
            or not approval_id
            or not isinstance(approved_by, str)
            or not approved_by
        ):
            return Result.failure(AdapterError(ErrorClass.UNAUTHORISED, "exact_approval_evidence_missing"))
        try:
            lease = await self._issuer.materialize(
                tenant_id=context.tenant_id,
                owner_id=context.on_behalf_of or context.actor,
                device_id=params["device_id"],
                camera_id=params["camera_id"],
                verb=verb,
                raw_action=_action(params),
                approval_id=approval_id,
                approved_by=approved_by,
                run_ids=tuple(
                    value
                    for value in (context.run_id, context.parent_run_id)
                    if value
                ),
            )
        except CameraLeaseIssueError as exc:
            return Result.failure(_adapter_error(exc))
        return Result.success({
            "status": "leased",
            "lease_id": lease.id,
            "device_id": lease.device_id,
            "camera_id": lease.camera_id,
            "verb": lease.verb,
            "expires_at": lease.expires_at.isoformat(),
        })

    async def health(self) -> str:
        return "ok"


def build_camera_lease_adapter(store: Any, signer: Any) -> CameraLeaseAdapter:
    return CameraLeaseAdapter(CameraLeaseIssuer(store, signer))


__all__ = ["CAMERA_LEASE_VERBS", "CameraLeaseAdapter", "build_camera_lease_adapter", "camera_lease_specs"]
