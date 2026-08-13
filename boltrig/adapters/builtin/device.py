"""Ordinary dispatcher adapter for signed, exact-action desktop-device leases."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
)
from boltrig.device_leases import DeviceLeaseIssueError, DeviceLeaseIssuer
from boltrig.models import AdapterFailure, InvocationContext
from boltrig.models.device_actions import (
    MAX_ARG_BYTES,
    MAX_ARGS,
    MAX_DIRECTORY_ENTRIES,
    MAX_FILE_BYTES,
    MAX_PATH_BYTES,
)

DEVICE_VERBS = (
    "device.file.list",
    "device.file.read",
    "device.file.write",
    "device.command.run",
)

_OPAQUE_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "pattern": "^[A-Za-z0-9_-]+$",
}
_RELATIVE_PATH = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_PATH_BYTES,
}
_OPTIONAL_RELATIVE_PATH = {
    "type": ["string", "null"],
    "minLength": 1,
    "maxLength": MAX_PATH_BYTES,
}
_LEASE_OUTPUT = {
    "type": "object",
    "properties": {
        "status": {"const": "leased"},
        "lease_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "device_id": _OPAQUE_ID,
        "root_id": _OPAQUE_ID,
        "verb": {"type": "string", "enum": list(DEVICE_VERBS)},
        "expires_at": {"type": "string", "minLength": 1, "maxLength": 64},
    },
    "required": [
        "status",
        "lease_id",
        "device_id",
        "root_id",
        "verb",
        "expires_at",
    ],
    "additionalProperties": False,
}
_BASE_PROPERTIES = {
    "device_id": _OPAQUE_ID,
    "root_id": _OPAQUE_ID,
}


def _input(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**_BASE_PROPERTIES, **properties},
        "required": ["device_id", "root_id", *required],
        "additionalProperties": False,
    }


def _file_list_spec(common: dict[str, Any]) -> VerbSpec:
    return VerbSpec(
        verb_id="device.file.list",
        input_schema=_input(
            {
                "relative_path": _OPTIONAL_RELATIVE_PATH,
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_DIRECTORY_ENTRIES,
                },
            },
            ["relative_path", "max_entries"],
        ),
        description=(
            "Issue one signed lease for a bounded single-directory "
            "metadata listing."
        ),
        **common,
    )


def device_specs() -> list[VerbSpec]:
    """The full capability is data: schemas, HIGH consequence and rate bounds."""
    common: dict[str, Any] = {
        "noun_id": "device",
        "output_schema": _LEASE_OUTPUT,
        "consequence": "high",
        "rate_limit": {"per": "minute", "max": 30, "scope": "tenant"},
        "idempotency_mode": "cacheable",
    }
    return [
        _file_list_spec(common),
        VerbSpec(
            verb_id="device.file.read",
            input_schema=_input(
                {
                    "relative_path": _RELATIVE_PATH,
                    "max_bytes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_FILE_BYTES,
                    },
                },
                ["relative_path", "max_bytes"],
            ),
            description="Issue one signed lease for a bounded relative file read.",
            **common,
        ),
        VerbSpec(
            verb_id="device.file.write",
            input_schema=_input(
                {
                    "relative_path": _RELATIVE_PATH,
                    "content_digest": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "byte_size": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_FILE_BYTES,
                    },
                    "overwrite": {"type": "boolean"},
                },
                ["relative_path", "content_digest", "byte_size", "overwrite"],
            ),
            description="Issue one signed digest-bound relative file write lease.",
            **common,
        ),
        VerbSpec(
            verb_id="device.command.run",
            input_schema=_input(
                {
                    "argv": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_ARGS,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_ARG_BYTES,
                        },
                    },
                    "cwd_relative": {
                        "type": ["string", "null"],
                        "minLength": 1,
                        "maxLength": MAX_PATH_BYTES,
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 300,
                    },
                },
                ["argv", "cwd_relative", "timeout_seconds"],
            ),
            description="Issue one signed argv-only command lease on an opted-in root.",
            **common,
        ),
    ]


def _action(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in params.items()
        if key not in {"device_id", "root_id"}
    }


def _adapter_error(exc: DeviceLeaseIssueError) -> AdapterError:
    if exc.status_code == 403:
        kind = ErrorClass.UNAUTHORISED
    elif exc.status_code == 404:
        kind = ErrorClass.NOT_FOUND
    elif exc.status_code == 409:
        kind = ErrorClass.CONFLICT
    elif exc.status_code == 503:
        kind = ErrorClass.UNAVAILABLE
    else:
        kind = ErrorClass.INVALID
    return AdapterError(kind, exc.reason)


class DeviceLeaseAdapter:
    id = "device"
    version = "1.0.0"
    runtime = "script"

    def __init__(self, issuer: DeviceLeaseIssuer) -> None:
        self._issuer = issuer

    def describe(self) -> list[VerbSpec]:
        return device_specs()

    async def approval_context(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> dict[str, Any]:
        """Bind approval to mutable root scope, verifier identity and cancellation."""
        try:
            return await self._issuer.resource_context(
                context.tenant_id,
                context.on_behalf_of or context.actor,
                params["device_id"],
                params["root_id"],
                verb,
                _action(params),
                run_ids=tuple(
                    value
                    for value in (context.run_id, context.parent_run_id)
                    if value
                ),
            )
        except DeviceLeaseIssueError as exc:
            raise AdapterFailure(
                exc.reason, status_code=exc.status_code, reason=exc.reason
            ) from exc

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if verb not in DEVICE_VERBS:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "unsupported_device_verb")
            )
        expected = context.extra.get("approval_resource_context")
        fingerprint = context.extra.get("approval_request_fingerprint")
        approval_id = context.extra.get("approval_request_id")
        approved_by = context.extra.get("approved_by")
        try:
            current = await self.approval_context(verb, params, context)
        except AdapterFailure as exc:
            return Result.failure(
                _adapter_error(
                    DeviceLeaseIssueError(exc.reason, exc.status_code)
                )
            )
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or expected != current
            or not isinstance(approval_id, str)
            or not approval_id
            or not isinstance(approved_by, str)
            or not approved_by
        ):
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "exact_approval_evidence_missing")
            )
        try:
            lease = await self._issuer.materialize(
                tenant_id=context.tenant_id,
                owner_id=context.on_behalf_of or context.actor,
                device_id=params["device_id"],
                root_id=params["root_id"],
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
        except DeviceLeaseIssueError as exc:
            return Result.failure(_adapter_error(exc))
        return Result.success(
            {
                "status": "leased",
                "lease_id": lease.id,
                "device_id": lease.device_id,
                "root_id": lease.root_id,
                "verb": lease.verb,
                "expires_at": lease.expires_at.isoformat(),
            }
        )

    async def health(self) -> str:
        return "ok"


def build_device_adapter(store: Any, signer: Any) -> DeviceLeaseAdapter:
    return DeviceLeaseAdapter(DeviceLeaseIssuer(store, signer))


__all__ = [
    "DEVICE_VERBS",
    "DeviceLeaseAdapter",
    "build_device_adapter",
    "device_specs",
]
