"""Pure standards-first camera capability negotiation.

The native layer owns USB/AVFoundation access and supplies a bounded JSON
probe result. This module turns that evidence into a stable local profile. It
never performs capture, writes controls, opens HID, or loads executable vendor
code. Descriptor support and physical proof remain separate fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from .profiles import CameraProfileRegistry


class CameraDiscoveryError(ValueError):
    """Raised when a native probe result cannot be safely interpreted."""


class CapabilityState(StrEnum):
    UNSUPPORTED = "unsupported"
    ADVERTISED = "advertised"
    READABLE = "readable"
    PROVEN = "proven"
    UNKNOWN = "unknown"
    INVALID_DESCRIPTOR = "invalid_descriptor"
    PERMISSION_REQUIRED = "permission_required"
    DEVICE_BUSY = "device_busy"
    UNAVAILABLE = "unavailable"


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CameraDiscoveryError(f"{name}_must_be_object")
    return value


def _bool(value: object) -> bool:
    return value is True or value == 1


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
class Capability:
    state: CapabilityState
    source: str
    evidence: tuple[str, ...] = ()
    implementation: str | None = None
    reason: str | None = None
    limits: dict[str, Any] = field(default_factory=dict)

    @property
    def supported(self) -> bool:
        return self.state not in {
            CapabilityState.UNSUPPORTED,
            CapabilityState.UNKNOWN,
            CapabilityState.UNAVAILABLE,
        }

    @property
    def proven(self) -> bool:
        return self.state is CapabilityState.PROVEN

    def __post_init__(self) -> None:
        if not self.source:
            raise CameraDiscoveryError("capability_source_required")
        if self.state is CapabilityState.PROVEN and not self.evidence:
            raise CameraDiscoveryError("proven_capability_requires_evidence")

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state.value,
            "source": self.source,
        }
        if self.evidence:
            result["evidence"] = list(self.evidence)
        if self.implementation is not None:
            result["implementation"] = self.implementation
        if self.reason is not None:
            result["reason"] = self.reason
        if self.limits:
            result["limits"] = dict(self.limits)
        return result


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
    manufacturer = str(device.get("manufacturer") or "Unknown")
    product = str(device.get("product_name") or "USB Camera")
    usb_vid = _usb_id(device.get("vendor_id") or usb.get("vendor_id"), "vendor_id")
    usb_pid = _usb_id(device.get("product_id") or usb.get("product_id"), "product_id")
    fingerprint = descriptor_fingerprint(root)
    if camera_id is None:
        camera_id = "camera_" + hashlib.sha256(
            f"{usb_vid:04x}:{usb_pid:04x}:{fingerprint}".encode("ascii")
        ).hexdigest()[:32]
    if not isinstance(camera_id, str) or not camera_id.startswith("camera_"):
        raise CameraDiscoveryError("invalid_camera_id")

    profile = profiles.match(usb_vid, usb_pid) if profiles is not None else None
    controls = _object(usb_video.get("controls", {}), "controls")
    pan_tilt = _control(controls, "pan_tilt_absolute")
    focus = _control(controls, "focus_absolute")
    zoom = _control(controls, "zoom_absolute")
    privacy = _control(controls, "privacy")
    hid = _object(usb.get("hid", {}), "hid")
    interface_summary = _interface_summary(usb)
    video_supported = _bool(usb_video.get("uvc")) or _bool(video.get("uvc"))
    audio_supported = _bool(audio.get("uac")) or _bool(usb_video.get("audio_interface_present"))
    formats: list[Any] = []
    for item in video.get("devices", []) if isinstance(video.get("devices"), list) else []:
        if isinstance(item, Mapping):
            formats.extend(item.get("formats", []) if isinstance(item.get("formats"), list) else [])
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
    capabilities = {
        "video": _video_capability(video_supported, formats, snapshot_proven),
        "audio": Capability(
            state=CapabilityState.READABLE if audio_supported else CapabilityState.UNSUPPORTED,
            source="uac_descriptor" if audio_supported else "native_discovery",
            evidence=("uac_interface", "audio_formats") if audio_supported else (),
            implementation="uac" if audio_supported else None,
            reason=None if audio_supported else "no_standard_uac_audio",
        ),
        "snapshot": Capability(
            state=CapabilityState.PROVEN if snapshot_proven else (CapabilityState.ADVERTISED if snapshot_supported else CapabilityState.UNSUPPORTED),
            source="capture_test" if snapshot_proven else "uvc_descriptor",
            evidence=("one_frame_capture", "decode_success", "frame_discarded") if snapshot_proven else (("uvc_video_device",) if snapshot_supported else ()),
            implementation="uvc" if snapshot_supported else None,
            reason=None if snapshot_supported else "video_capture_not_available",
        ),
        "pan": _ptz_capability(
            pan_tilt,
            axis="pan",
            proven=pan_proven,
            test_evidence=_test_evidence(root, "pan"),
        ),
        "tilt": _ptz_capability(
            pan_tilt,
            axis="tilt",
            proven=tilt_proven,
            test_evidence=_test_evidence(root, "tilt"),
        ),
        "zoom": _scalar_capability(zoom),
        "focus": _scalar_capability(focus),
        "privacy": _privacy_capability(privacy),
        "tracking": Capability(
            state=CapabilityState.UNKNOWN if _bool(hid.get("present")) else CapabilityState.UNSUPPORTED,
            source="vendor_hid_descriptor" if _bool(hid.get("present")) else "native_discovery",
            evidence=("hid_present", "hid_descriptor_read") if _bool(hid.get("present")) else (),
            implementation=(profile.vendor_capabilities.get("tracking") if profile is not None and profile.trusted else None),
            reason="vendor_test_required" if _bool(hid.get("present")) else "no_vendor_tracking_evidence",
        ),
    }
    control_transports = []
    if _control_supported(pan_tilt) or _control_supported(zoom) or _control_supported(focus) or _control_supported(privacy):
        control_transports.append("uvc")
    if _bool(hid.get("present")):
        control_transports.append("hid")
    driver: dict[str, Any] = {
        "video": profile_standard.get("video", "uvc") if video_supported else "none",
        "audio": profile_standard.get("audio", "uac") if audio_supported else "none",
        "controls": control_transports,
    }
    if profile is not None and profile.trusted:
        driver["extras"] = f"vendor-profile:{profile.id}"
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
        interfaces=interface_summary,
        warnings=tuple(warnings),
        profile_quirks=profile.quirks if profile is not None and profile.trusted else {},
    )


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


def _control(controls: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = controls.get(name, {})
    return value if isinstance(value, Mapping) else {}


def _control_supported(control: Mapping[str, Any]) -> bool:
    return _bool(control.get("supported"))


def _control_readable(control: Mapping[str, Any]) -> bool:
    return _bool(control.get("readable"))


def _physical_test(probe: Mapping[str, Any], name: str) -> bool:
    tests = probe.get("physical_tests", {})
    if not isinstance(tests, Mapping):
        return False
    evidence = tests.get(name, {})
    if not isinstance(evidence, Mapping):
        return False
    if name == "snapshot":
        return _bool(evidence.get("passed"))
    return _bool(evidence.get("passed")) and _bool(evidence.get("restoration_succeeded"))


def _test_evidence(probe: Mapping[str, Any], name: str) -> tuple[str, ...]:
    tests = probe.get("physical_tests", {})
    evidence = tests.get(name, {}) if isinstance(tests, Mapping) else {}
    values = evidence.get("evidence", []) if isinstance(evidence, Mapping) else []
    return tuple(str(value) for value in values if isinstance(value, str))


def _video_capability(supported: bool, formats: list[Any], snapshot_proven: bool) -> Capability:
    if not supported:
        return Capability(CapabilityState.UNSUPPORTED, "native_discovery", reason="no_standard_uvc_video")
    return Capability(
        CapabilityState.PROVEN if snapshot_proven else CapabilityState.ADVERTISED,
        "capture_test" if snapshot_proven else "uvc_descriptor",
        evidence=("one_frame_capture",) if snapshot_proven else ("uvc_video_device",),
        implementation="uvc",
        limits={"formats": formats[:128]},
    )


def _ptz_capability(
    control: Mapping[str, Any],
    *,
    axis: str,
    proven: bool,
    test_evidence: tuple[str, ...],
) -> Capability:
    supported = _control_supported(control)
    readable = _control_readable(control)
    if not supported:
        return Capability(CapabilityState.UNSUPPORTED, "uvc_descriptor", reason="ptz_not_advertised")
    limits: dict[str, Any] = {}
    for key in ("min", "max", "step"):
        value = control.get(key)
        if isinstance(value, list) and len(value) == 2:
            limits[key] = value[0 if axis == "pan" else 1]
    state = CapabilityState.PROVEN if proven and readable else CapabilityState.READABLE if readable else CapabilityState.ADVERTISED
    evidence = ["uvc_descriptor", "get_info_read"]
    if _bool(control.get("writable")):
        evidence.append("get_info_write")
    if readable and all(key in control for key in ("min", "max", "step", "current")):
        evidence.append("range_read")
    if proven:
        evidence.extend(test_evidence or ("set_cur_success", "readback_match", "physical_verification", "restoration_match"))
    return Capability(state, "uvc_descriptor", tuple(dict.fromkeys(evidence)), "uvc", limits=limits)


def _scalar_capability(control: Mapping[str, Any]) -> Capability:
    if not _control_supported(control):
        return Capability(CapabilityState.UNSUPPORTED, "uvc_descriptor", reason="control_not_advertised")
    readable = _control_readable(control)
    return Capability(
        CapabilityState.READABLE if readable else CapabilityState.ADVERTISED,
        "uvc_descriptor",
        ("uvc_descriptor", "get_info_read") if readable else ("uvc_descriptor",),
        "uvc",
        limits={key: control[key] for key in ("min", "max", "step", "default", "current") if control.get(key) is not None},
    )


def _invalid_boolean_descriptor(control: Mapping[str, Any]) -> bool:
    values = [control.get(key) for key in ("min", "max", "step", "default", "current")]
    return any(isinstance(value, int) and value not in {0, 1} for value in values)


def _privacy_capability(control: Mapping[str, Any]) -> Capability:
    if not _control_supported(control):
        return Capability(CapabilityState.UNSUPPORTED, "uvc_descriptor", reason="privacy_not_advertised")
    if _invalid_boolean_descriptor(control):
        return Capability(
            CapabilityState.INVALID_DESCRIPTOR,
            "uvc_descriptor",
            ("uvc_descriptor", "get_info_read", "boolean_domain_invalid"),
            "uvc",
            reason="boolean_values_outside_0_or_1",
        )
    if _control_readable(control):
        return Capability(CapabilityState.READABLE, "uvc_descriptor", ("uvc_descriptor", "get_info_read"), "uvc")
    return Capability(CapabilityState.ADVERTISED, "uvc_descriptor", ("uvc_descriptor",), "uvc")
