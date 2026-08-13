"""Camera and presence as first-class Boltrig services, governed in one place.

THE DAEMON IS ALWAYS BOLTRIG'S, WHOEVER IS WATCHING (docs/SPEC-character-bundle.md).
Jarvis watching, Maya watching, Bella watching: same camerad, same observation
loop, same presence, same retention/quiet-hours/gesture policy.  Nothing about
the *watching* is character-specific, so consent, retention and device choice
live here -- one module, one UI, one audit trail -- and never inside a plugin a
user might install without reading.

A BUNDLE SHIPS CONFIGURATION, NEVER EXECUTABLE CODE.  A character DECLARES that
it would like the camera (``capabilities.camera.wanted`` in its manifest) and is
refused honestly when the user has it off.  That refusal lives next door in
``sensing_capability``; this module is what is STORED, that one is what is SAID.

EVERY PARSE FAILS TOWARD OFF.  This mirrors ``parse_approval_posture`` failing
toward ``risk_based``: a corrupt or half-written row can never *widen* consent.
A camera whose settings will not parse is a camera that is off.

WHY user_settings AND NOT A NEW TABLE.  These are per-user preferences with a
consent surface, which is exactly what ``user_settings`` already is, and
``agentic.approval_posture`` is the working precedent for a consent control with
a UI toggle persisted through it.  The dotted namespace matches ``agentic.*``,
``appearance.*`` and ``a11y.*``.

WHERE THE PROCESS LIVES.  The kernel runs in a Linux VM and cannot see a USB
camera; that is why ``apps/worker/src-tauri/src/camera_uvc.m`` and the
``/v1/device-agent/{device_id}/camera-*`` lease plane exist at all.  So "camerad
belongs to Boltrig" means OWNERSHIP AND CONFIGURATION move to the kernel while
the process stays on the host beside the hardware, reading ``sensing-config``
through the authenticated device-agent transport.  No new listener, and nothing
leaves the host.
"""

from __future__ import annotations

from typing import Any

from boltrig.models import UserSetting

# --- the keys --------------------------------------------------------------

CAMERA_ENABLED = "sensing.camera.enabled"
CAMERA_BINDING = "sensing.camera.binding"
CAMERA_RETENTION_HOURS = "sensing.camera.retention_hours"
CAMERA_QUIET_HOURS = "sensing.camera.quiet_hours"
PRESENCE_ENABLED = "sensing.presence.enabled"
ENROLLMENT = "sensing.enrollment"

#: Every key this module owns.  ``PUT /v1/me/settings`` refuses all of them, the
#: same way it already refuses ``agentic.approval_posture``: a validated route
#: that can be bypassed by writing its raw key is not a validated route.
SENSING_KEYS = frozenset({
    CAMERA_ENABLED,
    CAMERA_BINDING,
    CAMERA_RETENTION_HOURS,
    CAMERA_QUIET_HOURS,
    PRESENCE_ENABLED,
    ENROLLMENT,
})

#: THE ENROLLED FACE IS KERNEL DATA, NEVER BUNDLE DATA.
#:
#: Anchor images are the CHARACTER's face and travel with a bundle.  The enrolled
#: face is the USER's, and a character is a thing you might share -- a shared
#: character must not carry someone's biometrics.  This names the key no bundle
#: export may ever read; the export side of the rule is enforced in
#: ``sdks/web/src/characterBundle.ts`` (``exportCharacterBundle``), which builds
#: its output from an allow-list for the same reason.
#:
#: Deliberately NOT excluded from ``GET /v1/me/export``: that route hands the
#: user their own data back, which is the opposite of the risk here.
NEVER_LEAVES_THE_KERNEL = frozenset({ENROLLMENT})

# --- defaults --------------------------------------------------------------

#: Both defaults are OFF.  A fresh Boltrig does not watch you until someone says
#: so in a UI.
DEFAULT_CAMERA_ENABLED = False
DEFAULT_PRESENCE_ENABLED = False
DEFAULT_RETENTION_HOURS = 24
DEFAULT_QUIET_START = 22
DEFAULT_QUIET_END = 8

MIN_RETENTION_HOURS = 1
MAX_RETENTION_HOURS = 168

#: The capture thresholds, served to the host daemons so ``capture_policy.py``
#: stops being the place a companion's repo configures the user's hardware.
#: These are the numbers that module holds today; it keeps them as fail-safe
#: defaults for when the kernel is unreachable.
CAPTURE_THRESHOLDS: dict[str, Any] = {
    "thumb": 64,
    "dark_mean": 12.0,
    "change": 6.0,
    "static_diff": 4.0,
    "interval": 30,
    "dark_pause_s": 900,
    "gesture_pause_s": 1800,
}

#: How long a host daemon may honour a cached ``sensing-config`` after the kernel
#: stops answering.  Past it the watching stands down but the device is NOT
#: released by bouncing camerad: recovery from a wedged UVC device is a physical
#: replug, so a transient kernel outage must never cost one.  Indefinitely stale
#: consent is the unacceptable failure; a stopped capture loop is the cheap one.
CONFIG_MAX_STALE_S = 3600

_SHA256 = "0123456789abcdef"


# --- parsing ---------------------------------------------------------------


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _digest(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    return value if all(ch in _SHA256 for ch in value) else None


def parse_retention_hours(value: Any) -> int:
    """Hours, bounded.  Anything else is the default.

    ``bool`` is an ``int`` in Python and ``True`` would otherwise become one
    hour, so it is rejected explicitly rather than clamped into legitimacy.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_RETENTION_HOURS
    if value < MIN_RETENTION_HOURS or value > MAX_RETENTION_HOURS:
        return DEFAULT_RETENTION_HOURS
    return value


def _hour(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 0 <= value <= 23 else default


def parse_quiet_hours(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"start": DEFAULT_QUIET_START, "end": DEFAULT_QUIET_END}
    return {
        "start": _hour(value.get("start"), DEFAULT_QUIET_START),
        "end": _hour(value.get("end"), DEFAULT_QUIET_END),
    }


def parse_binding(value: Any) -> dict[str, Any] | None:
    """The chosen camera, or ``None``.

    A binding that will not parse is no binding, which reads as
    ``camera_not_bound`` rather than as permission to pick a camera for the user.
    """
    if not isinstance(value, dict):
        return None
    camera_id = value.get("camera_id")
    device_id = value.get("device_id")
    if not isinstance(camera_id, str) or not camera_id:
        return None
    if not isinstance(device_id, str) or not device_id:
        return None
    binding: dict[str, Any] = {"camera_id": camera_id, "device_id": device_id}
    fingerprint = _digest(value.get("descriptor_fingerprint"))
    if fingerprint:
        binding["descriptor_fingerprint"] = fingerprint
    label = value.get("label")
    if isinstance(label, str) and label:
        binding["label"] = label[:256]
    return binding


def parse_enrollment(value: Any) -> dict[str, Any] | None:
    """The kernel's record of the enrolled face.  METADATA ONLY, never vectors.

    ``threshold`` is room-calibrated and has no baked-in fallback anywhere in the
    estate: ``presence.py`` hard-exits without one rather than guessing, and this
    parser keeps that property by returning ``None`` when it is missing or out of
    range.  A threshold guessed on the user's behalf is a false-accept rate
    nobody measured, presented as a fact about who is in the room.

    ``far_measured`` is carried so the UI can say honestly that the false-accept
    rate was never measured, which is the standing reason an armed guard is still
    deferred.
    """
    if not isinstance(value, dict):
        return None
    digest = _digest(value.get("digest"))
    threshold = value.get("threshold")
    if digest is None:
        return None
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return None
    if not 0.0 < float(threshold) <= 1.0:
        return None
    count = value.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        count = 0
    basis = value.get("basis")
    return {
        "digest": digest,
        "threshold": float(threshold),
        "count": count,
        "far_measured": _bool(value.get("far_measured"), False),
        "basis": basis if isinstance(basis, str) else None,
    }


# --- reads -----------------------------------------------------------------


async def sensing_settings(store: Any, tenant_id: str, user_id: str) -> dict[str, Any]:
    """Every sensing setting for one user, parsed and defaulted.

    ``source`` distinguishes a deliberate choice from the safe default, exactly
    as ``approval_posture_for`` does, so the UI never presents "off because
    nobody has decided" as "off because you decided".
    """
    rows = {
        row.key: row.value
        for row in await store.list_user_settings(tenant_id, user_id)
        if row.key in SENSING_KEYS
    }
    return {
        "camera": {
            "enabled": _bool(rows.get(CAMERA_ENABLED), DEFAULT_CAMERA_ENABLED),
            "source": "user_override" if CAMERA_ENABLED in rows else "safe_default",
            "binding": parse_binding(rows.get(CAMERA_BINDING)),
            "retention_hours": parse_retention_hours(rows.get(CAMERA_RETENTION_HOURS)),
            "quiet_hours": parse_quiet_hours(rows.get(CAMERA_QUIET_HOURS)),
        },
        "presence": {
            "enabled": _bool(rows.get(PRESENCE_ENABLED), DEFAULT_PRESENCE_ENABLED),
            "source": "user_override" if PRESENCE_ENABLED in rows else "safe_default",
        },
        "enrollment": parse_enrollment(rows.get(ENROLLMENT)),
    }


def sensing_config(settings: dict[str, Any]) -> dict[str, Any]:
    """The effective capture policy for one device's daemons.

    This is what replaces the constants in ``capture_policy.py``: camerad,
    capture and presence stop being configured by files inside a companion's
    repo, and the numbers arrive from the kernel the user controls.  The daemons
    re-read it every ``interval``, so switching the camera off in the UI bites
    within about thirty seconds rather than at the next restart -- the same rule
    the spec sets for restricted-scene permission, checked at selection time and
    never cached.
    """
    camera = settings["camera"]
    binding = camera["binding"] or {}
    enrollment = settings.get("enrollment") or {}
    return {
        "v": 1,
        "camera": {
            "enabled": camera["enabled"],
            "camera_id": binding.get("camera_id"),
            "descriptor_fingerprint": binding.get("descriptor_fingerprint"),
            "retention_hours": camera["retention_hours"],
            "quiet_hours": camera["quiet_hours"],
        },
        "presence": {
            # Presence cannot run without a room-calibrated threshold, so the
            # config never reports it enabled when there is not one. The daemon
            # would hard-exit; refusing here means it never starts instead.
            "enabled": bool(
                settings["presence"]["enabled"] and enrollment.get("threshold") is not None
            ),
            "enrollment_digest": enrollment.get("digest"),
            "threshold": enrollment.get("threshold"),
        },
        "thresholds": dict(CAPTURE_THRESHOLDS),
        "max_stale_s": CONFIG_MAX_STALE_S,
    }


# --- writes ----------------------------------------------------------------


async def _put(store: Any, tenant_id: str, user_id: str, key: str, value: Any) -> None:
    await store.upsert_user_setting(
        UserSetting(tenant_id=tenant_id, user_id=user_id, key=key, value=value)
    )


async def persist_camera_settings(
    store: Any,
    tenant_id: str,
    user_id: str,
    *,
    enabled: bool | None = None,
    binding: dict[str, Any] | None = None,
    clear_binding: bool = False,
    retention_hours: int | None = None,
    quiet_hours: dict[str, int] | None = None,
) -> None:
    if enabled is not None:
        await _put(store, tenant_id, user_id, CAMERA_ENABLED, enabled)
    if clear_binding:
        await _put(store, tenant_id, user_id, CAMERA_BINDING, None)
    elif binding is not None:
        await _put(store, tenant_id, user_id, CAMERA_BINDING, binding)
    if retention_hours is not None:
        await _put(store, tenant_id, user_id, CAMERA_RETENTION_HOURS, retention_hours)
    if quiet_hours is not None:
        await _put(store, tenant_id, user_id, CAMERA_QUIET_HOURS, quiet_hours)


async def persist_presence_enabled(
    store: Any, tenant_id: str, user_id: str, enabled: bool
) -> None:
    await _put(store, tenant_id, user_id, PRESENCE_ENABLED, enabled)


async def persist_enrollment(
    store: Any, tenant_id: str, user_id: str, enrollment: dict[str, Any] | None
) -> None:
    """Record, or forget, the enrolled face.

    Forgetting writes ``None`` rather than deleting the row: ``user_settings``
    has no delete in the store contract, and an explicit null is anyway the
    honest record that a face was enrolled here once and is not any more.
    """
    await _put(store, tenant_id, user_id, ENROLLMENT, enrollment)


__all__ = [
    "CAMERA_BINDING",
    "CAMERA_ENABLED",
    "CAMERA_QUIET_HOURS",
    "CAMERA_RETENTION_HOURS",
    "CAPTURE_THRESHOLDS",
    "CONFIG_MAX_STALE_S",
    "ENROLLMENT",
    "MAX_RETENTION_HOURS",
    "MIN_RETENTION_HOURS",
    "NEVER_LEAVES_THE_KERNEL",
    "PRESENCE_ENABLED",
    "SENSING_KEYS",
    "parse_binding",
    "parse_enrollment",
    "parse_quiet_hours",
    "parse_retention_hours",
    "persist_camera_settings",
    "persist_enrollment",
    "persist_presence_enabled",
    "sensing_config",
    "sensing_settings",
]
