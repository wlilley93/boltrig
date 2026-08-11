"""Standards-first camera discovery and capability negotiation."""

from .discovery import (
    CameraDiscovery,
    CameraDiscoveryError,
    Capability,
    CapabilityState,
    descriptor_fingerprint,
    discover_camera,
)
from .cache import CameraCacheError, CameraKnowledgeCache
from .backend import CameraBackend, CameraOperation, CameraOperationState
from .platform import CameraDiscoveryService, CameraObservation, CameraPlatform
from .profiles import CameraProfile, CameraProfileRegistry, load_profile

__all__ = [
    "CameraDiscovery",
    "CameraDiscoveryError",
    "CameraProfile",
    "CameraProfileRegistry",
    "Capability",
    "CapabilityState",
    "CameraCacheError",
    "CameraKnowledgeCache",
    "CameraBackend",
    "CameraOperation",
    "CameraOperationState",
    "CameraDiscoveryService",
    "CameraObservation",
    "CameraPlatform",
    "descriptor_fingerprint",
    "discover_camera",
    "load_profile",
]
