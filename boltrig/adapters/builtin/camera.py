"""Governed read-only camera discovery surface.

The native Worker supplies a provider implementation. This adapter owns only
the boring, schema-bound camera verbs; it does not open USB, invoke commands,
or interpret vendor reports. Mutating verbs are intentionally absent from v1.
"""

from __future__ import annotations

from typing import Any, Protocol

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import InvocationContext


CAMERA_VERBS = (
    "camera.device.list",
    "camera.device.status",
    "camera.device.capabilities",
    "camera.snapshot",
)
_CAMERA_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "pattern": "^camera_[A-Fa-f0-9]{32}$",
}
_CAPABILITY_OUTPUT = {"type": "object"}


class CameraProvider(Protocol):
    """Host-side, read-only provider contract."""

    async def list_cameras(self) -> list[dict[str, Any]]: ...

    async def camera_status(self, camera_id: str) -> dict[str, Any] | None: ...

    async def camera_capabilities(self, camera_id: str) -> dict[str, Any] | None: ...

    async def snapshot(self, camera_id: str) -> dict[str, Any] | None: ...


class CameraDiscoveryAdapter:
    id = "camera"
    version = "1.0.0"
    runtime = "file"

    def __init__(self, provider: CameraProvider) -> None:
        self._provider = provider

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="camera.device.list",
                noun_id="camera",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                output_schema={"type": "object", "required": ["cameras"], "properties": {"cameras": {"type": "array"}}, "additionalProperties": False},
                consequence="low",
                description="List locally discovered cameras and evidence-backed capabilities.",
                rate_limit={"per": "minute", "max": 60, "scope": "tenant"},
            ),
            VerbSpec(
                verb_id="camera.device.status",
                noun_id="camera",
                input_schema={"type": "object", "properties": {"camera_id": _CAMERA_ID}, "required": ["camera_id"], "additionalProperties": False},
                output_schema=_CAPABILITY_OUTPUT,
                consequence="low",
                description="Read one camera's local discovery status without changing the device.",
                rate_limit={"per": "minute", "max": 120, "scope": "tenant"},
            ),
            VerbSpec(
                verb_id="camera.device.capabilities",
                noun_id="camera",
                input_schema={"type": "object", "properties": {"camera_id": _CAMERA_ID}, "required": ["camera_id"], "additionalProperties": False},
                output_schema=_CAPABILITY_OUTPUT,
                consequence="low",
                description="Read the evidence-backed capability projection for one local camera.",
                rate_limit={"per": "minute", "max": 120, "scope": "tenant"},
            ),
            VerbSpec(
                verb_id="camera.snapshot",
                noun_id="camera",
                input_schema={"type": "object", "properties": {"camera_id": _CAMERA_ID}, "required": ["camera_id"], "additionalProperties": False},
                output_schema=_CAPABILITY_OUTPUT,
                consequence="high",
                description="Request one local camera snapshot through the native provider.",
                rate_limit={"per": "minute", "max": 30, "scope": "tenant"},
            ),
        ]

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del credential, context
        if verb not in CAMERA_VERBS:
            return Result.failure(AdapterError(ErrorClass.INVALID, "unsupported_camera_verb"))
        if verb == "camera.device.list":
            return Result.success({"cameras": await self._provider.list_cameras()})
        camera_id = params.get("camera_id")
        if not isinstance(camera_id, str):
            return Result.failure(AdapterError(ErrorClass.INVALID, "invalid_camera_id"))
        if verb == "camera.device.status":
            output = await self._provider.camera_status(camera_id)
        elif verb == "camera.device.capabilities":
            output = await self._provider.camera_capabilities(camera_id)
        else:
            capability_view = await self._provider.camera_capabilities(camera_id)
            if capability_view is None:
                return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "camera_not_found"))
            capability_map = capability_view.get("capabilities", {})
            snapshot = capability_map.get("snapshot", {}) if isinstance(capability_map, dict) else {}
            if not isinstance(snapshot, dict) or snapshot.get("state") != "proven":
                return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, "camera_snapshot_unproven"))
            output = await self._provider.snapshot(camera_id)
        if output is None:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "camera_not_found"))
        return Result.success(output)

    async def health(self) -> str:
        return "ok"


def build(provider: CameraProvider) -> CameraDiscoveryAdapter:
    return CameraDiscoveryAdapter(provider)
