"""Declarative, local-only camera profile metadata.

Profiles identify likely standard transports and describe vendor capabilities;
they never contain executable code. A matching profile is only a routing hint:
current-device evidence still decides whether a capability is proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
import tomllib


class CameraProfileError(ValueError):
    """Raised when a profile is malformed or contains executable metadata."""


_ALLOWED_TOP_LEVEL = {
    "id",
    "label",
    "match",
    "standard",
    "vendor",
    "known",
    "capabilities",
    "unsupported_until_proven",
    "quirks",
}
_FORBIDDEN_KEYS = {
    "command",
    "download",
    "executable",
    "exec",
    "module",
    "script",
    "url",
}


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CameraProfileError(f"profile_{field_name}_must_be_object")
    return value


def _string(value: object, field_name: str, *, max_length: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise CameraProfileError(f"invalid_profile_{field_name}")
    return value


def _usb_id(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise CameraProfileError(f"invalid_profile_{field_name}")
    try:
        if isinstance(value, str):
            parsed = int(value, 0)
        elif isinstance(value, int):
            parsed = value
        else:
            raise TypeError
    except (TypeError, ValueError):
        raise CameraProfileError(f"invalid_profile_{field_name}") from None
    if not 0 <= parsed <= 0xFFFF:
        raise CameraProfileError(f"invalid_profile_{field_name}")
    return parsed


def _reject_executable_metadata(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise CameraProfileError("executable_profile_metadata_forbidden")
            _reject_executable_metadata(child)
    elif isinstance(value, list):
        for child in value:
            _reject_executable_metadata(child)


@dataclass(frozen=True)
class CameraProfile:
    """A non-executable profile used for matching and standard routing hints."""

    id: str
    label: str
    usb_vid: int
    usb_pid: int
    standard: dict[str, str] = field(default_factory=dict)
    vendor_transport: str | None = None
    vendor_report_id: int | None = None
    vendor_capabilities: dict[str, str] = field(default_factory=dict)
    known: dict[str, Any] = field(default_factory=dict)
    unsupported_until_proven: tuple[str, ...] = ()
    quirks: dict[str, Any] = field(default_factory=dict)
    trusted: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, trusted: bool = False) -> "CameraProfile":
        _reject_executable_metadata(raw)
        unknown = set(raw) - _ALLOWED_TOP_LEVEL
        if unknown:
            raise CameraProfileError("unknown_profile_field")
        match = _mapping(raw.get("match"), "match")
        standard_raw = _mapping(raw.get("standard", {}), "standard")
        vendor = _mapping(raw.get("vendor", {}), "vendor")
        known = _mapping(raw.get("known", {}), "known")
        capabilities = _mapping(raw.get("capabilities", {}), "capabilities")
        unsupported = raw.get("unsupported_until_proven", {})
        unsupported_map = _mapping(unsupported, "unsupported_until_proven")
        quirks = _mapping(raw.get("quirks", {}), "quirks")
        profile_id = _string(raw.get("id"), "id")
        label = _string(raw.get("label", profile_id), "label")
        standard: dict[str, str] = {}
        for key, value in standard_raw.items():
            standard[_string(key, "standard_key")] = _string(value, "standard_value")

        vendor_transport = vendor.get("transport")
        if vendor_transport is not None:
            vendor_transport = _string(vendor_transport, "vendor_transport")
        vendor_report_id = vendor.get("report_id")
        if vendor_report_id is not None:
            if isinstance(vendor_report_id, bool):
                raise CameraProfileError("invalid_profile_vendor_report_id")
            try:
                vendor_report_id = int(vendor_report_id, 0) if isinstance(vendor_report_id, str) else int(vendor_report_id)
            except (TypeError, ValueError):
                raise CameraProfileError("invalid_profile_vendor_report_id") from None
            if not 0 <= vendor_report_id <= 0xFF:
                raise CameraProfileError("invalid_profile_vendor_report_id")

        vendor_capabilities: dict[str, str] = {}
        for key, value in capabilities.items():
            capability = _mapping(value, "capability")
            implementation = capability.get("implementation")
            if implementation is not None:
                vendor_capabilities[_string(key, "capability_key")] = _string(
                    implementation, "capability_implementation"
                )

        return cls(
            id=profile_id,
            label=label,
            usb_vid=_usb_id(match.get("vid", match.get("usb_vid")), "usb_vid"),
            usb_pid=_usb_id(match.get("pid", match.get("usb_pid")), "usb_pid"),
            standard=standard,
            vendor_transport=vendor_transport,
            vendor_report_id=vendor_report_id,
            vendor_capabilities=vendor_capabilities,
            known=dict(known),
            unsupported_until_proven=tuple(
                _string(key, "unsupported_capability")
                for key, value in unsupported_map.items()
                if value is True
            ),
            quirks=dict(quirks),
            trusted=trusted,
        )

    def matches(self, usb_vid: int, usb_pid: int) -> bool:
        return self.usb_vid == usb_vid and self.usb_pid == usb_pid

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "match": {"vid": f"0x{self.usb_vid:04x}", "pid": f"0x{self.usb_pid:04x}"},
            "standard": dict(self.standard),
            "known": dict(self.known),
            "unsupported_until_proven": {
                key: True for key in self.unsupported_until_proven
            },
            "quirks": dict(self.quirks),
            "vendor": {
                key: value
                for key, value in {
                    "transport": self.vendor_transport,
                    "report_id": self.vendor_report_id,
                }.items()
                if value is not None
            },
            "capabilities": {
                key: {"implementation": value}
                for key, value in self.vendor_capabilities.items()
            },
            "trusted": self.trusted,
        }


def load_profile(path: str | Path, *, trusted_ids: Iterable[str] = ()) -> CameraProfile:
    profile_path = Path(path)
    try:
        raw = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CameraProfileError("camera_profile_unreadable") from exc
    profile_id = raw.get("id")
    trusted = isinstance(profile_id, str) and profile_id in set(trusted_ids)
    return CameraProfile.from_mapping(raw, trusted=trusted)


class CameraProfileRegistry:
    """An in-process registry of local declarative profiles."""

    def __init__(self, profiles: Iterable[CameraProfile] = ()) -> None:
        self._profiles: dict[str, CameraProfile] = {}
        for profile in profiles:
            self.add(profile)

    def add(self, profile: CameraProfile) -> None:
        if profile.id in self._profiles:
            raise CameraProfileError("duplicate_camera_profile")
        if len(self._profiles) >= 256:
            raise CameraProfileError("too_many_camera_profiles")
        self._profiles[profile.id] = profile

    def match(self, usb_vid: int, usb_pid: int) -> CameraProfile | None:
        for profile in self._profiles.values():
            if profile.matches(usb_vid, usb_pid):
                return profile
        return None

    @classmethod
    def load_dir(
        cls,
        directory: str | Path,
        *,
        trusted_ids: Iterable[str] = (),
    ) -> "CameraProfileRegistry":
        """Load only local TOML metadata; never import or execute a profile."""
        root = Path(directory)
        if not root.is_dir():
            raise CameraProfileError("camera_profile_directory_unavailable")
        trusted = set(trusted_ids)
        paths = sorted(root.rglob("*.toml"))
        if len(paths) > 256:
            raise CameraProfileError("too_many_camera_profiles")
        return cls(load_profile(path, trusted_ids=trusted) for path in paths)

    def __len__(self) -> int:
        return len(self._profiles)

    def __iter__(self) -> Iterator[CameraProfile]:
        return iter(self._profiles.values())
