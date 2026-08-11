"""Pure standards-first camera capability negotiation.

The native layer owns USB/AVFoundation access and supplies a bounded JSON
probe result. This module turns that evidence into a stable local profile. It
never performs capture, writes controls, opens HID, or loads executable vendor
code. Descriptor support and physical proof remain separate fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

from .capabilities import (
    CameraDiscoveryError,
    Capability,
    CapabilityState,
    _bool,
    _capability_map,
    _control,
    _control_supported,
    _invalid_boolean_descriptor,
    _object,
    _physical_test,
)
from .profiles import CameraProfileRegistry




def _usb_id(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise CameraDiscoveryError(f"invalid_{name}")
    try:
        if isinstance(value, str):
            parsed = int(value, 0)
        elif isinstance(value, int):
            parsed = value
        else:
            raise TypeError
    except (TypeError, ValueError):
        raise CameraDiscoveryError(f"invalid_{name}") from None
    if not 0 <= parsed <= 0xFFFF:
        raise CameraDiscoveryError(f"invalid_{name}")
    return parsed


def _hex_digest(value: object) -> str | None:
    if isinstance(value, str) and len(value) == 64:
        try:
            int(value, 16)
        except ValueError:
            return None
        return value.lower()
    return None


def _without_sensitive_fields(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _without_sensitive_fields(child)
            for key, child in value.items()
            if str(key).lower()
            not in {"serial", "serial_number", "registry_path", "uuid", "raw_hid_bytes"}
        }
    if isinstance(value, list):
        return [_without_sensitive_fields(child) for child in value]
    return value


def descriptor_fingerprint(probe: Mapping[str, Any]) -> str:
    """Hash immutable interface/descriptor shape, excluding mutable state."""
    supplied = _hex_digest(probe.get("descriptor_fingerprint"))
    if supplied is not None:
        return supplied
    usb = _object(probe.get("usb", {}), "usb")
    material = {
        "interfaces": usb.get("interfaces", []),
        "video": _object(usb.get("video", {}), "usb_video"),
        "hid": _object(usb.get("hid", {}), "usb_hid"),
        "audio": _object(usb.get("audio", {}), "usb_audio"),
        "network_interface": usb.get("network_interface", False),
        "other_interfaces": usb.get("other_interfaces", []),
    }
    # Current focus/PTZ/exposure values must never make a new hardware family.
    if isinstance(material["video"], Mapping):
        video = dict(material["video"])
        controls = video.get("controls")
        if isinstance(controls, Mapping):
            video["controls"] = {
                name: {
                    key: child
                    for key, child in control.items()
                    if key not in {"current", "default", "readback"}
                }
                if isinstance(control, Mapping)
                else control
                for name, control in controls.items()
            }
        material["video"] = video
    encoded = json.dumps(
        _without_sensitive_fields(material),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()




@dataclass(frozen=True)
class CameraDiscovery:
    schema_version: int
    camera_id: str
    label: str
    manufacturer: str
    product: str
    usb_vid: int
    usb_pid: int
    descriptor_fingerprint: str
    profile_id: str | None
    profile_trusted: bool
    driver: dict[str, Any]
    capabilities: dict[str, Capability]
    interfaces: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    profile_quirks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "v": self.schema_version,
            "camera_id": self.camera_id,
            "label": self.label,
            "transport": dict(self.driver),
            "interfaces": dict(self.interfaces),
            "usb": {
                "vid": f"0x{self.usb_vid:04x}",
                "pid": f"0x{self.usb_pid:04x}",
                "descriptor_fingerprint": self.descriptor_fingerprint,
            },
            "profile": {
                "id": self.profile_id,
                "trusted": self.profile_trusted,
                "quirks": dict(self.profile_quirks),
            },
            "capabilities": {
                name: capability.as_dict()
                for name, capability in self.capabilities.items()
            },
            "warnings": list(self.warnings),
            "allowed_verbs": self.allowed_verbs(),
        }

    def allowed_verbs(self) -> list[str]:
        """Return only verbs justified by the current evidence."""
        verbs = [
            "camera.device.list",
            "camera.device.status",
            "camera.device.capabilities",
        ]
        snapshot = self.capabilities.get("snapshot")
        if snapshot and snapshot.proven:
            verbs.append("camera.snapshot")
        pan = self.capabilities.get("pan")
        tilt = self.capabilities.get("tilt")
        if pan and tilt and pan.state in {CapabilityState.READABLE, CapabilityState.PROVEN} and tilt.state in {CapabilityState.READABLE, CapabilityState.PROVEN}:
            verbs.append("camera.ptz.get")
        if pan and tilt and pan.proven and tilt.proven:
            verbs.append("camera.ptz.set")
        privacy = self.capabilities.get("privacy")
        if privacy and privacy.proven:
            verbs.extend(["camera.privacy.enable", "camera.privacy.disable"])
        tracking = self.capabilities.get("tracking")
        if tracking and tracking.proven:
            verbs.append("camera.tracking.set")
        return verbs


def discover_camera(
    probe: Mapping[str, Any],
    *,
    profiles: CameraProfileRegistry | None = None,
    camera_id: str | None = None,
) -> CameraDiscovery:
    """Build one safe capability map from a native read-only probe result."""
    root = _object(probe, "probe")
    device = _object(root.get("device"), "device")
    if not _bool(device.get("present")):
        raise CameraDiscoveryError("camera_not_present")
    usb = _object(root.get("usb"), "usb")
    usb_video = _object(usb.get("video", {}), "usb_video")
    video = _object(root.get("video", {}), "video")
    audio = _object(root.get("audio", {}), "audio")
    fingerprint = descriptor_fingerprint(root)
    camera_id, manufacturer, product, usb_vid, usb_pid = _identity(
        device, usb, fingerprint, camera_id,
    )

    profile = profiles.match(usb_vid, usb_pid) if profiles is not None else None
    controls = _object(usb_video.get("controls", {}), "controls")
    pan_tilt = _control(controls, "pan_tilt_absolute")
    focus = _control(controls, "focus_absolute")
    zoom = _control(controls, "zoom_absolute")
    privacy = _control(controls, "privacy")
    hid = _object(usb.get("hid", {}), "hid")
    video_supported, audio_supported, formats = _media_support(usb_video, video, audio)
    snapshot_supported = video_supported and bool(formats)
    snapshot_proven = _physical_test(root, "snapshot")
    pan_proven = _physical_test(root, "pan")
    tilt_proven = _physical_test(root, "tilt")
    profile_standard = profile.standard if profile is not None else {}
    warnings: list[str] = []
    if profile is not None and not profile.trusted:
        warnings.append("matching_profile_untrusted_vendor_metadata_inactive")
    if _control_supported(privacy) and _invalid_boolean_descriptor(privacy):
        warnings.append("privacy_descriptor_invalid")
    capabilities = _capability_map(
        root,
        profile=profile,
        hid=hid,
        pan_tilt=pan_tilt,
        zoom=zoom,
        focus=focus,
        privacy=privacy,
        video_supported=video_supported,
        audio_supported=audio_supported,
        snapshot_supported=snapshot_supported,
        snapshot_proven=snapshot_proven,
        pan_proven=pan_proven,
        tilt_proven=tilt_proven,
        formats=formats,
    )
    control_transports = []
    if _control_supported(pan_tilt) or _control_supported(zoom) or _control_supported(focus) or _control_supported(privacy):
        control_transports.append("uvc")
    if _bool(hid.get("present")):
        control_transports.append("hid")
    driver = _driver_map(
        profile, profile_standard, control_transports,
        video_supported=video_supported, audio_supported=audio_supported,
    )
    return CameraDiscovery(
        schema_version=1,
        camera_id=camera_id,
        label=product,
        manufacturer=manufacturer,
        product=product,
        usb_vid=usb_vid,
        usb_pid=usb_pid,
        descriptor_fingerprint=fingerprint,
        profile_id=profile.id if profile is not None else None,
        profile_trusted=profile.trusted if profile is not None else False,
        driver=driver,
        capabilities=capabilities,
        interfaces=_interface_summary(usb),
        warnings=tuple(warnings),
        profile_quirks=profile.quirks if profile is not None and profile.trusted else {},
    )





def _media_support(
    usb_video: Mapping[str, Any],
    video: Mapping[str, Any],
    audio: Mapping[str, Any],
) -> tuple[bool, bool, list[Any]]:
    """Whether the standard video/audio classes are present, and the formats offered.

    Both descriptor locations are consulted: a camera may declare UVC on the USB
    interface, on the video node, or both, and disagreeing on which one counts
    would make the same device read differently on different platforms.
    """
    video_supported = _bool(usb_video.get("uvc")) or _bool(video.get("uvc"))
    audio_supported = _bool(audio.get("uac")) or _bool(usb_video.get("audio_interface_present"))
    formats: list[Any] = []
    devices = video.get("devices", [])
    for item in devices if isinstance(devices, list) else []:
        if isinstance(item, Mapping):
            entries = item.get("formats", [])
            formats.extend(entries if isinstance(entries, list) else [])
    return video_supported, audio_supported, formats


def _identity(
    device: Mapping[str, Any],
    usb: Mapping[str, Any],
    fingerprint: str,
    camera_id: str | None,
) -> tuple[str, str, str, int, int]:
    """Names, USB ids, and the id this camera is keyed by.

    A caller may supply the id (rebinding a known camera); otherwise it is
    derived from vid/pid plus the descriptor fingerprint, so the same physical
    device keys the same way and a changed descriptor keys differently.
    """
    manufacturer = str(device.get("manufacturer") or "Unknown")
    product = str(device.get("product_name") or "USB Camera")
    usb_vid = _usb_id(device.get("vendor_id") or usb.get("vendor_id"), "vendor_id")
    usb_pid = _usb_id(device.get("product_id") or usb.get("product_id"), "product_id")
    if camera_id is None:
        camera_id = "camera_" + hashlib.sha256(
            f"{usb_vid:04x}:{usb_pid:04x}:{fingerprint}".encode("ascii")
        ).hexdigest()[:32]
    if not isinstance(camera_id, str) or not camera_id.startswith("camera_"):
        raise CameraDiscoveryError("invalid_camera_id")
    return camera_id, manufacturer, product, usb_vid, usb_pid


def _driver_map(
    profile: Any,
    profile_standard: Mapping[str, Any],
    control_transports: list[str],
    *,
    video_supported: bool,
    audio_supported: bool,
) -> dict[str, Any]:
    """Which standard transport carries each stream. Vendor extras only when trusted."""
    driver: dict[str, Any] = {
        "video": profile_standard.get("video", "uvc") if video_supported else "none",
        "audio": profile_standard.get("audio", "uac") if audio_supported else "none",
        "controls": control_transports,
    }
    if profile is not None and profile.trusted:
        driver["extras"] = f"vendor-profile:{profile.id}"
    return driver



def _interface_summary(usb: Mapping[str, Any]) -> dict[str, Any]:
    classes: list[str] = []
    raw_interfaces = usb.get("interfaces", [])
    if isinstance(raw_interfaces, list):
        for item in raw_interfaces[:64]:
            if isinstance(item, Mapping):
                value = item.get("class")
                if isinstance(value, str) and value not in classes:
                    classes.append(value)
    network = _bool(usb.get("network_interface")) or any(
        value in {"communications", "cdc_data", "network", "wireless_controller"}
        for value in classes
    )
    storage = any(value in {"mass_storage", "storage"} for value in classes)
    serial = any(value in {"serial", "cdc_data"} for value in classes)
    vendor_specific = any(value in {"vendor_specific", "vendor-defined"} for value in classes)
    return {
        "classes": classes,
        "network": network,
        "storage": storage,
        "serial": serial,
        "vendor_specific": vendor_specific,
    }


