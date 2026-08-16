"""Owner-facing routes for the camera and presence services.

Shaped on ``approval_posture_routes``, and for the same reason: this is a
CONSENT surface.  Every mutating route opens with the interactive-human guard,
so a delegated agent -- or a character -- can never turn the user's camera on.
That guard is the mechanism behind the spec's rule that a downloaded character
can only ask a question through a daemon YOU own and YOU can switch off.

``GET /v1/sensing/capability`` is the character-facing half: it answers with a
REASON rather than raising, and never substitutes anything for a capability the
user has turned off.  It is authenticated as the USER and carries no character
identity, so it governs consent and NOT declaration -- see the caveat on the
handler and the module docstring of ``sensing_capability``.
"""

from __future__ import annotations

from typing import Any

from fastapi import Query
from fastapi.responses import JSONResponse

from boltrig.config.dev_posture import is_interactive_credential

from .sensing_capability import (
    capability_decision,
    presence_blocker,
    sensing_view,
)
from .sensing_policy import (
    MAX_RETENTION_HOURS,
    MIN_RETENTION_HOURS,
    parse_binding,
    parse_quiet_hours,
    parse_retention_hours,
    persist_camera_settings,
    persist_enrollment,
    persist_presence_enabled,
    sensing_settings,
)


def _denied() -> JSONResponse:
    return JSONResponse(
        {"status": "denied", "reason": "an interactive human session is required"},
        status_code=403,
    )


def _error(reason: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": reason}, status_code=status)


def _human(p: Any) -> bool:
    return p.actor_tier == "human" and is_interactive_credential(p.credential_kind)


async def _view(k: Any, p: Any) -> dict[str, Any]:
    return sensing_view(await sensing_settings(k.store, p.tenant_id, p.subject))


async def _ok(k: Any, p: Any) -> JSONResponse:
    """Every write answers with the whole settled state, not an ack.

    The UI applies the change optimistically and reverts on anything but ``ok``;
    handing back the full view means a clamp, a refused binding or a presence
    that could not be enabled is visible at once rather than at the next read.
    """
    return JSONResponse({"status": "ok", **await _view(k, p)})


async def _known_camera(store: Any, tenant_id: str, user_id: str, binding: dict) -> bool:
    """Is this camera one the device agent actually published?

    Mirrors ``validated_capability_routes`` refusing an endpoint id with no
    ``model_endpoints`` row: a camera id nobody advertised is refused AT WRITE
    TIME, not discovered at capture time when the answer would be a daemon that
    silently never sees anything.
    """
    lister = getattr(store, "list_camera_bindings", None)
    if lister is None:
        return False
    rows = await lister(tenant_id, user_id, binding["device_id"])
    return any(row.camera_id == binding["camera_id"] for row in rows or ())


def _camera_updates(body: dict) -> tuple[dict[str, Any], JSONResponse | None]:
    """Validate a camera body into keyword updates, or refuse it by name."""
    updates: dict[str, Any] = {}
    enabled = body.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        return updates, _error("enabled must be a boolean")
    updates["enabled"] = enabled

    if "retention_hours" in body:
        retention = parse_retention_hours(body.get("retention_hours"))
        if retention != body.get("retention_hours"):
            return updates, _error(
                "retention_hours must be an integer "
                f"{MIN_RETENTION_HOURS}..{MAX_RETENTION_HOURS}"
            )
        updates["retention_hours"] = retention

    if "quiet_hours" in body:
        updates["quiet_hours"] = parse_quiet_hours(body["quiet_hours"])

    if "camera_id" in body or "device_id" in body:
        if body.get("camera_id") is None:
            updates["clear_binding"] = True
        else:
            binding = parse_binding(body)
            if binding is None:
                return updates, _error("camera_id and device_id are required together")
            updates["binding"] = binding
    return updates, None


def _register_camera_route(app, P, K, audit) -> None:
    @app.put("/v1/me/sensing/camera")
    async def put_sensing_camera(body: dict, k=K, p=P) -> JSONResponse:
        if not _human(p):
            return _denied()
        updates, refusal = _camera_updates(body)
        if refusal is not None:
            return refusal
        binding = updates.get("binding")
        if binding is not None and not await _known_camera(
            k.store, p.tenant_id, p.subject, binding
        ):
            # Named, not swallowed: the same shape as
            # model_endpoint_binding_unavailable.
            return _error("camera_binding_unavailable", 409)
        await persist_camera_settings(k.store, p.tenant_id, p.subject, **updates)
        await audit(
            k, p, "sensing.camera.update",
            {
                "enabled": updates.get("enabled"),
                "bound": binding is not None,
                "cleared": updates.get("clear_binding", False),
                "retention_hours": updates.get("retention_hours"),
            },
        )
        return await _ok(k, p)


def _register_presence_routes(app, P, K, audit) -> None:
    @app.put("/v1/me/sensing/presence")
    async def put_sensing_presence(body: dict, k=K, p=P) -> JSONResponse:
        if not _human(p):
            return _denied()
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _error("enabled must be a boolean")
        settings = await sensing_settings(k.store, p.tenant_id, p.subject)
        blocker = presence_blocker(settings)
        if enabled and blocker is not None:
            # Refusing rather than storing True keeps the kernel's answer and the
            # daemon's behaviour the same: presence hard-exits without a
            # room-calibrated threshold, so "on" would be a lie the UI told.
            return _error(blocker, 409)
        await persist_presence_enabled(k.store, p.tenant_id, p.subject, enabled)
        await audit(k, p, "sensing.presence.update", {"enabled": enabled})
        return await _ok(k, p)

    # Recording an enrolment is NOT here. It is published by the host agent over
    # the device transport (POST /v1/device-agent/{device_id}/sensing-enrollment),
    # the same way camera bindings are: the enrolment is produced by a tool on the
    # machine with the camera, which has no interactive browser session and must
    # not be given one. Forgetting it stays here, because forgetting is the user's
    # act and belongs where they can see it.
    @app.delete("/v1/me/sensing/enrollment")
    async def delete_sensing_enrollment(k=K, p=P) -> JSONResponse:
        if not _human(p):
            return _denied()
        # Presence goes off in the same request. Leaving it on with nothing to
        # recognise against would leave a daemon that starts and immediately
        # exits, which reads as broken rather than as forgotten.
        await persist_enrollment(k.store, p.tenant_id, p.subject, None)
        await persist_presence_enabled(k.store, p.tenant_id, p.subject, False)
        await audit(k, p, "sensing.enrollment.forget", {})
        return await _ok(k, p)


def _register_read_routes(app, P, K) -> None:
    @app.get("/v1/me/sensing")
    async def get_sensing(k=K, p=P) -> dict:
        return await _view(k, p)

    @app.get("/v1/sensing/capability")
    async def sensing_capability(
        capability: str = Query(..., max_length=64), k=K, p=P
    ) -> JSONResponse:
        """What a caller asking for this capability right now is told.

        Checked at USE, never cached: the answer changes the moment the user
        moves a toggle, and a client that cached it would keep watching after
        consent was withdrawn.

        **This route does not know which character is asking, and does not
        enforce declaration.**  ``p`` is the USER -- tenant, subject, credential
        kind -- and nothing on the request names a bundle.  The answer is
        therefore about the capability and the user's settings only: an
        undeclared character asking with the camera on is told ``granted``.  The
        Stage is what honours declaration (it asks for exactly the ids in
        ``wantsSensing``), and that is a constraint on the Stage rather than a
        boundary, since a character add-in shares its JavaScript realm.  The
        limitation, and what closing it would actually take, is written out in
        ``sensing_capability``'s module docstring; do not read this endpoint as
        the enforcement point.
        """
        settings = await sensing_settings(k.store, p.tenant_id, p.subject)
        decision = capability_decision(settings, capability)
        # 409, not 403: the user is permitted and has chosen off. 403 would read
        # as "you may not", which is a different and untrue statement. Matches
        # ModelEndpointUnavailable, the estate's precedent for "the configured
        # thing is not available".
        status = 200 if decision["status"] == "granted" else 409
        return JSONResponse(decision, status_code=status)


def register_sensing_routes(app, P, K, audit) -> None:
    _register_read_routes(app, P, K)
    _register_camera_route(app, P, K, audit)
    _register_presence_routes(app, P, K, audit)


__all__ = ["register_sensing_routes"]
