"""Canonical camera actions for camera-specific signed leases.

Camera leases deliberately do not carry a device root.  A camera binding is a
local hardware identity, and the descriptor fingerprint is signed alongside
the requested semantic PTZ target so a lease cannot silently move to another
camera or to a changed descriptor.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any

CAMERA_VERBS = ("camera.ptz.get", "camera.ptz.set")
MAX_CAMERA_ID_BYTES = 128
MAX_FINGERPRINT_BYTES = 64
MAX_CAMERA_ANGLE_MILLIDEGREES = 360_000_000
_CAMERA_ID = re.compile(r"^camera_[A-Fa-f0-9]{32}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def _normalise_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non_finite_camera_action")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalise_json(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("invalid_camera_action")
            key = unicodedata.normalize("NFC", raw_key)
            if key in result:
                raise ValueError("normalised_camera_action_key_collision")
            result[key] = _normalise_json(item)
        return result
    raise ValueError("invalid_camera_action")


def _digest(*, device_id: str, camera_id: str, verb: str, action: dict[str, Any]) -> str:
    payload = {
        "noun": "camera",
        "params": {"camera_id": camera_id, "device_id": device_id, **action},
        "verb": verb,
        "version": 1,
    }
    encoded = json.dumps(
        _normalise_json(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _camera_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > MAX_CAMERA_ID_BYTES
        or _CAMERA_ID.fullmatch(value) is None
    ):
        raise ValueError("invalid_camera_id")
    return value


def _fingerprint(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) != MAX_FINGERPRINT_BYTES
        or _FINGERPRINT.fullmatch(value) is None
    ):
        raise ValueError("invalid_camera_descriptor_fingerprint")
    return value


def _angle(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not -MAX_CAMERA_ANGLE_MILLIDEGREES <= value <= MAX_CAMERA_ANGLE_MILLIDEGREES
    ):
        raise ValueError("invalid_camera_angle")
    return value


def canonical_camera_action(
    device_id: str, camera_id: str, verb: str, raw: object
) -> tuple[dict[str, Any], str]:
    """Validate a bounded semantic PTZ action and return its exact digest."""
    if not isinstance(device_id, str) or not device_id or len(device_id) > 256:
        raise ValueError("invalid_device_id")
    camera_id = _camera_id(camera_id)
    if not isinstance(raw, dict):
        raise ValueError("camera_action_must_be_object")
    if verb == "camera.ptz.get":
        if set(raw) != {"descriptor_fingerprint"}:
            raise ValueError("unknown_camera_action_field")
        action: dict[str, Any] = {
            "descriptor_fingerprint": _fingerprint(raw["descriptor_fingerprint"]),
        }
    elif verb == "camera.ptz.set":
        if set(raw) != {"descriptor_fingerprint", "pan_millidegrees", "tilt_millidegrees"}:
            raise ValueError("unknown_camera_action_field")
        action = {
            "descriptor_fingerprint": _fingerprint(raw["descriptor_fingerprint"]),
            "pan_millidegrees": _angle(raw["pan_millidegrees"]),
            "tilt_millidegrees": _angle(raw["tilt_millidegrees"]),
        }
    else:
        raise ValueError("unsupported_camera_verb")
    return action, _digest(
        device_id=device_id, camera_id=camera_id, verb=verb, action=action
    )


__all__ = [
    "CAMERA_VERBS",
    "MAX_CAMERA_ANGLE_MILLIDEGREES",
    "canonical_camera_action",
]
