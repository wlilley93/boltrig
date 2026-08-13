"""The honest refusal: what a character is told when it asks to see.

A character DECLARES that it would like the camera and is REFUSED HONESTLY when
the user has it off (docs/SPEC-character-bundle.md).  Everything here exists so
that the refusal is a NAMED ANSWER rather than an exception, a crash, or -- the
failure this module is really written against -- a silent substitution.

Contrast ``familiar_phenotype_routes``, which answers *resting* on every failure
because a cosmetic side-channel must never teach a client to treat its absence
as a fault.  Sensing is the opposite case: the spec requires absent capability
to be VISIBLE, so this returns an explicit refusal object and the Worker draws
it.

Split from ``sensing_policy`` because they answer different questions: that
module is what is STORED, this one is what is SAID.

WHAT THIS MODULE DOES NOT DO -- read before trusting it (2026-08-13)
--------------------------------------------------------------------
**It does not enforce declaration, and it cannot.**  The spec's sentence is "a
character DECLARES capability usage and is refused honestly", and only the
second half happens here.  ``GET /v1/sensing/capability`` is authenticated as
the USER; the request carries a tenant, a subject and a credential kind, and
nothing whatsoever that identifies the calling character.  So this module can
answer "is this a capability this Boltrig offers" and "has the user turned it
on", and it cannot answer "did this character's bundle ask for it".

The former reason code ``capability_not_declared`` claimed otherwise: it fired
for any name outside :data:`CAPABILITIES`, and both its name and its copy said a
character had not declared something the kernel had never been told about.  It
is now :attr:`SensingRefusal.CAPABILITY_UNKNOWN`, which is the true statement.

Declaration is honoured ONE layer up, in the Worker: ``StageBody.useSensing``
asks for exactly the ids in the character's ``wantsSensing``, which
``characterFromBundle`` fills in from the manifest.  That is a real constraint on
the Stage and NOT a security boundary -- a character add-in shares the Worker's
JavaScript realm and can call ``client.sensingCapability`` for anything.

Making it a boundary is a bigger change than a reason code, and deliberately not
attempted here.  It needs, at minimum: a kernel-side record of which bundles a
user has installed and what each declared (a table and a migration -- note 0074
for ``sensing_enrollments`` is itself still outstanding); a character identity
threaded onto ``Principal`` under the same rule ``active_workspace_id`` follows,
re-authorised every request and never read from the request body; and an answer
to the part that is not merely plumbing -- a browser caller's claim of "I am
Maya" is unforgeable only if the proof lives somewhere the other characters in
the same realm cannot read it, which in one JS realm it does not.

**This costs no imagery.**  The endpoint returns a decision and never pixels,
frames or observations, and every capture path is gated on the user's own switch
rather than on who asked.  What is at stake is the honesty of the contract: an
undeclared character asking with the camera on is told ``granted``, and nothing
in this file should be read as preventing that.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class SensingRefusal(StrEnum):
    """One reason code per refusal, shared by the kernel, the daemons and the UI.

    ``CAMERAD_HOLDS_DEVICE`` is the string ``apps/worker/src-tauri/src/camera_uvc.m``
    already speaks; it is reused verbatim rather than given a synonym, because a
    second name for the same truth is how two layers start disagreeing about it.

    Every member is a refusal the kernel can actually reach.  The Worker adds one
    the kernel by construction cannot -- ``kernel_unreachable``, synthesised when
    the ask never arrives -- and it is absent here for that reason rather than by
    oversight.  ``capability_not_declared`` is likewise absent, and that one is a
    REMOVAL: see the module docstring for why no layer can honestly say it.
    """

    CAMERA_DISABLED = "camera_disabled"
    CAMERA_NOT_BOUND = "camera_not_bound"
    CAMERA_DEVICE_MISSING = "camera_device_missing"
    CAMERA_PAUSED_QUIET_HOURS = "camera_paused_quiet_hours"
    CAMERA_PAUSED_DARK = "camera_paused_dark"
    CAMERA_PAUSED_GESTURE = "camera_paused_gesture"
    CAMERAD_HOLDS_DEVICE = "camerad_holds_device"
    PRESENCE_DISABLED = "presence_disabled"
    PRESENCE_NOT_ENROLLED = "presence_not_enrolled"
    PRESENCE_NOT_CALIBRATED = "presence_not_calibrated"
    CAPABILITY_UNKNOWN = "capability_unknown"


#: What the UI says, in the user's words, for each refusal.  The daemon-side
#: pauses carry copy here too because the Worker renders them: a capability that
#: is absent because the lens is covered must read as differently from one that
#: is absent because consent was withdrawn.
REFUSAL_DETAIL: dict[str, str] = {
    SensingRefusal.CAMERA_DISABLED: (
        "The camera is turned off in Settings › Camera and presence."
    ),
    SensingRefusal.CAMERA_NOT_BOUND: (
        "The camera is on but no camera has been chosen yet."
    ),
    SensingRefusal.CAMERA_DEVICE_MISSING: (
        "The chosen camera is no longer attached to this computer."
    ),
    SensingRefusal.CAMERA_PAUSED_QUIET_HOURS: (
        "It is inside quiet hours, so nothing is being watched."
    ),
    SensingRefusal.CAMERA_PAUSED_DARK: (
        "The lens is covered or the room is dark, so the camera has stood down."
    ),
    SensingRefusal.CAMERA_PAUSED_GESTURE: (
        "You asked it to stop watching, and it has."
    ),
    SensingRefusal.CAMERAD_HOLDS_DEVICE: (
        "Another process is holding the camera."
    ),
    SensingRefusal.PRESENCE_DISABLED: (
        "Presence is turned off in Settings › Camera and presence."
    ),
    SensingRefusal.PRESENCE_NOT_ENROLLED: (
        "No face has been enrolled on this computer."
    ),
    SensingRefusal.PRESENCE_NOT_CALIBRATED: (
        "The enrolled face has no room-calibrated threshold, so presence cannot "
        "answer honestly."
    ),
    # Says only what the kernel knows.  The copy it replaced -- "this character
    # never asked for that capability" -- described a check nobody runs.
    SensingRefusal.CAPABILITY_UNKNOWN: (
        "This Boltrig has no such capability to give."
    ),
}

#: The capabilities a bundle may request.  Mirrors the manifest's
#: ``capabilities.camera`` / ``capabilities.presence``.
CAMERA_CAPABILITY = "camera_observations"
PRESENCE_CAPABILITY = "presence"
CAPABILITIES = (CAMERA_CAPABILITY, PRESENCE_CAPABILITY)


#: The refusals no switch in Settings can lift.  Everything else names
#: ``settings:sensing``, because a refusal that does not say where the user goes
#: reads as a defect rather than as a setting -- but pointing an unknown
#: capability name at Settings would send them looking for a control that cannot
#: exist, which is the same mistake in the other direction.
_NO_REMEDY = frozenset({SensingRefusal.CAPABILITY_UNKNOWN})


def _refusal(capability: str, reason: SensingRefusal) -> dict[str, Any]:
    decision = {
        "status": "refused",
        "capability": capability,
        "reason": reason.value,
        "detail": REFUSAL_DETAIL[reason],
    }
    if reason not in _NO_REMEDY:
        decision["remedy"] = "settings:sensing"
    return decision


def capability_decision(settings: dict[str, Any], capability: str) -> dict[str, Any]:
    """Answer a request for a sensing capability, with a REASON.

    ``status`` is ``refused``, never ``error``.  A user who turned the camera off
    got exactly what they asked for; that is a correct answer, not a fault.

    Presence is checked AFTER the camera, in that order deliberately: with the
    camera off, "presence is disabled" would be a true statement that hid the
    reason that actually applies.

    NOT "a character's request", despite what a caller may assume: nothing
    reaching this function says WHICH character asked, so every answer here is
    about the capability and the user's settings alone.  The ``declared``
    keyword this used to take is gone -- its only caller passed
    ``capability in CAPABILITIES``, so it dressed a name check as a declaration
    check.  See the module docstring.
    """
    if capability not in CAPABILITIES:
        return _refusal(capability, SensingRefusal.CAPABILITY_UNKNOWN)

    camera = settings["camera"]
    if not camera["enabled"]:
        return _refusal(capability, SensingRefusal.CAMERA_DISABLED)
    if camera["binding"] is None:
        return _refusal(capability, SensingRefusal.CAMERA_NOT_BOUND)

    if capability == PRESENCE_CAPABILITY:
        if not settings["presence"]["enabled"]:
            return _refusal(capability, SensingRefusal.PRESENCE_DISABLED)
        enrollment = settings.get("enrollment")
        if enrollment is None:
            return _refusal(capability, SensingRefusal.PRESENCE_NOT_ENROLLED)
        if enrollment.get("threshold") is None:
            return _refusal(capability, SensingRefusal.PRESENCE_NOT_CALIBRATED)

    return {"status": "granted", "capability": capability}


def presence_blocker(settings: dict[str, Any]) -> str | None:
    """Why presence cannot be turned on, or ``None`` when it can.

    The toggle is disabled with a STATED reason rather than silently accepting a
    value that would make the daemon hard-exit at start.
    """
    enrollment = settings.get("enrollment")
    if enrollment is None:
        return SensingRefusal.PRESENCE_NOT_ENROLLED.value
    if enrollment.get("threshold") is None:
        return SensingRefusal.PRESENCE_NOT_CALIBRATED.value
    return None


def sensing_view(settings: dict[str, Any]) -> dict[str, Any]:
    """The owner-facing projection.

    The enrolment is reported as presence, count, threshold and whether the
    false-accept rate was measured -- never as anything that could reconstruct a
    face.  ``capabilities`` states, per capability, what a character asking right
    now would be told, so the settings surface and the refusal path cannot drift.
    """
    enrollment = settings.get("enrollment")
    return {
        "camera": dict(settings["camera"]),
        "presence": {**settings["presence"], "blocked_by": presence_blocker(settings)},
        "enrollment": {
            "present": enrollment is not None,
            "count": (enrollment or {}).get("count", 0),
            "threshold": (enrollment or {}).get("threshold"),
            "far_measured": (enrollment or {}).get("far_measured", False),
            # Stated in the projection rather than only in prose, so a client
            # cannot read this object and conclude it is bundle-shaped data.
            "exportable": False,
        },
        "capabilities": [
            capability_decision(settings, capability) for capability in CAPABILITIES
        ],
    }


__all__ = [
    "CAMERA_CAPABILITY",
    "CAPABILITIES",
    "PRESENCE_CAPABILITY",
    "REFUSAL_DETAIL",
    "SensingRefusal",
    "capability_decision",
    "presence_blocker",
    "sensing_view",
]
