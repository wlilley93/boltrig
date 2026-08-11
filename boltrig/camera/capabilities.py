"""The capability vocabulary, and the rules that decide each capability's state.

Split out of discovery.py so that module stays inside the 400-line structural
floor, and because the dependency runs one way: this module defines what a
capability IS, discovery decides which ones a given probe yields.

Descriptor support and physical proof stay separate throughout — ADVERTISED
means the descriptor claims it, PROVEN means something actually moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class CameraDiscoveryError(ValueError):
    """Raised when a native probe result cannot be safely interpreted."""


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CameraDiscoveryError(f"{name}_must_be_object")
    return value


def _bool(value: object) -> bool:
    return value is True or value == 1

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

def _capability_map(
    root: Mapping[str, Any],
    *,
    profile: Any,
    hid: Mapping[str, Any],
    pan_tilt: Mapping[str, Any],
    zoom: Mapping[str, Any],
    focus: Mapping[str, Any],
    privacy: Mapping[str, Any],
    video_supported: bool,
    audio_supported: bool,
    snapshot_supported: bool,
    snapshot_proven: bool,
    pan_proven: bool,
    tilt_proven: bool,
    formats: list[Any],
) -> dict[str, Capability]:
    """Every capability the probe supports a claim about, and on what evidence."""
    hid_present = _bool(hid.get("present"))
    tracking_impl = (
        profile.vendor_capabilities.get("tracking")
        if profile is not None and profile.trusted
        else None
    )
    return {
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
            state=CapabilityState.UNKNOWN if hid_present else CapabilityState.UNSUPPORTED,
            source="vendor_hid_descriptor" if hid_present else "native_discovery",
            evidence=("hid_present", "hid_descriptor_read") if hid_present else (),
            implementation=tracking_impl,
            reason="vendor_test_required" if hid_present else "no_vendor_tracking_evidence",
        ),
    }
