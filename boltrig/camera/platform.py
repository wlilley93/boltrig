"""Platform-neutral input and orchestration seam for camera discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .cache import CameraKnowledgeCache
from .discovery import CameraDiscovery, discover_camera, descriptor_fingerprint
from .profiles import CameraProfileRegistry


@dataclass(frozen=True)
class CameraObservation:
    """One safe native observation; the hardware key never leaves the Worker."""

    hardware_key: str
    probe: Mapping[str, Any]


class CameraPlatform(Protocol):
    """OS-specific read-only camera enumeration contract."""

    async def enumerate_cameras(self) -> list[CameraObservation]: ...


class CameraDiscoveryService:
    """Turn platform observations into bound, cached semantic discoveries."""

    def __init__(
        self,
        platform: CameraPlatform,
        cache: CameraKnowledgeCache,
        *,
        profiles: CameraProfileRegistry | None = None,
    ) -> None:
        self._platform = platform
        self._cache = cache
        self._profiles = profiles

    async def discover(self) -> list[CameraDiscovery]:
        observations = await self._platform.enumerate_cameras()
        if len(observations) > 64:
            raise ValueError("too_many_cameras")
        discoveries: list[CameraDiscovery] = []
        for observation in observations:
            fingerprint = descriptor_fingerprint(observation.probe)
            discovery = discover_camera(
                observation.probe,
                profiles=self._profiles,
                camera_id=self._cache.bind(
                    hardware_key=observation.hardware_key,
                    usb_vid=_probe_usb_id(observation.probe, "vendor_id"),
                    usb_pid=_probe_usb_id(observation.probe, "product_id"),
                    fingerprint=fingerprint,
                ),
            )
            self._cache.record(discovery)
            discoveries.append(discovery)
        return discoveries


def _probe_usb_id(probe: Mapping[str, Any], key: str) -> int:
    device = probe.get("device")
    if not isinstance(device, Mapping):
        raise ValueError("camera_observation_device_invalid")
    value = device.get(key)
    if value is None:
        usb = probe.get("usb")
        value = usb.get(key) if isinstance(usb, Mapping) else None
    if isinstance(value, bool) or value is None:
        raise ValueError("camera_observation_usb_identity_missing")
    try:
        return int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise ValueError("camera_observation_usb_identity_invalid") from None
