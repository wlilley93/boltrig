"""Fail-closed readiness projection for the configured Codex runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from boltrig.config.environment import is_truthy
from boltrig.release_mode import configured_release_mode


def codex_runtime_enabled(env: Mapping[str, str]) -> bool:
    """Whether this process has explicitly opted into the trusted Codex lane.

    The binary and stack-root paths may be baked into an image that deliberately
    keeps Codex off.  Only the trusted-lane flag enables the runtime, and the
    composition wall separately rejects missing paths or an unlawful posture.
    """

    return is_truthy(env.get("BOLTRIG_CODEX_TRUSTED"))


def manifest_requests_codex(manifest: Any | None) -> bool:
    """Whether the immutable boot manifest declares any Codex-backed runtime."""
    if manifest is None:
        return False
    profiles = list(getattr(manifest, "ephemeral_runtimes", ()) or ())
    hierarchy = getattr(manifest, "hierarchy", None)
    if hierarchy is not None:
        tier1 = getattr(hierarchy, "tier1", None)
        if tier1 is not None:
            profiles.append(tier1)
        profiles.extend(getattr(hierarchy, "tier2", ()) or ())
    return any(getattr(profile, "runtime", None) == "codex" for profile in profiles)


def codex_release_mode_posture(env: Mapping[str, str]) -> tuple[str, str | None]:
    """Project release mode onto Codex without weakening its admission wall."""
    try:
        mode = configured_release_mode(env)
    except ValueError:
        return "invalid", None
    if mode == "core":
        if codex_runtime_enabled(env):
            return "conflict", mode
        return "disabled", mode
    return "inherit", mode


def codex_runtime_check(
    env: Mapping[str, str], production: bool, *, manifest: Any | None = None
) -> dict[str, Any]:
    release_posture, release_mode = codex_release_mode_posture(env)
    if release_posture == "invalid":
        return {
            "status": "failed",
            "required": True,
            "reason": "invalid_release_mode",
        }
    if release_posture == "conflict":
        return {
            "status": "failed",
            "required": True,
            "reason": "release_mode_conflict",
            "release_mode": release_mode,
        }
    if release_posture == "disabled":
        return {
            "status": "disabled",
            "required": False,
            "reason": "core_release_mode",
            "release_mode": release_mode,
        }
    if not (codex_runtime_enabled(env) or manifest_requests_codex(manifest)):
        return {"status": "disabled", "required": False, "reason": "not_configured"}

    from boltrig.observability.codex_admission import codex_release_posture

    posture = codex_release_posture()
    blocker_count = len(posture["quarantined_preflight_blockers"])
    if not production:
        return {
            "status": "test_only",
            "required": False,
            "reason": "production_gate_closed",
            "blocker_count": blocker_count,
        }
    ready = posture["status"] == "ready"
    result: dict[str, Any] = {
        "status": "ok" if ready else "failed",
        "required": True,
        "blocker_count": blocker_count,
    }
    if not ready:
        result["reason"] = "production_gate_closed"
    return result


__all__ = [
    "codex_runtime_check",
    "codex_runtime_enabled",
    "codex_release_mode_posture",
    "manifest_requests_codex",
]
