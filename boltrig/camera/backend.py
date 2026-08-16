"""Manufacturer-neutral semantic camera backend contract.

Platform implementations (AVFoundation, Media Foundation, V4L2/PipeWire) and
standard protocol drivers implement this boundary. The public operation result
is intentionally explicit; callers must not turn an unavailable or unproven
operation into a success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .discovery import CameraDiscovery


class CameraOperationState(StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    UNPROVEN = "unproven"
    PERMISSION_REQUIRED = "permission_required"
    DEVICE_BUSY = "device_busy"
    DISCONNECTED = "disconnected"
    INVALID_STATE = "invalid_state"
    EXECUTION_FAILED = "execution_failed"


@dataclass(frozen=True)
class CameraOperation:
    state: CameraOperationState
    value: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"state": self.state.value}
        if self.value:
            result["value"] = dict(self.value)
        if self.error is not None:
            result["error"] = self.error
        return result


class CameraBackend(Protocol):
    """Semantic backend shared by all camera manufacturers."""

    async def discover(self) -> list[CameraDiscovery]: ...

    async def bind(self, camera_id: str) -> CameraOperation: ...

    async def unbind(self, camera_id: str) -> CameraOperation: ...

    async def status(self, camera_id: str) -> CameraOperation: ...

    async def capabilities(self, camera_id: str) -> CameraOperation: ...

    async def snapshot(self, camera_id: str) -> CameraOperation: ...

    async def ptz_get(self, camera_id: str) -> CameraOperation: ...

    async def ptz_set(self, camera_id: str, *, pan: int, tilt: int) -> CameraOperation: ...

    async def zoom_get(self, camera_id: str) -> CameraOperation: ...

    async def zoom_set(self, camera_id: str, *, value: int) -> CameraOperation: ...

    async def focus_get(self, camera_id: str) -> CameraOperation: ...

    async def focus_set(self, camera_id: str, *, value: int) -> CameraOperation: ...

    async def tracking_get(self, camera_id: str) -> CameraOperation: ...

    async def tracking_set(self, camera_id: str, *, enabled: bool) -> CameraOperation: ...

    async def privacy_get(self, camera_id: str) -> CameraOperation: ...

    async def privacy_enable(self, camera_id: str) -> CameraOperation: ...

    async def privacy_disable(self, camera_id: str) -> CameraOperation: ...
