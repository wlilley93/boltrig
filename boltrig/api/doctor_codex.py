"""Static production-admission check for a requested Codex runtime."""

from __future__ import annotations

from collections.abc import Mapping

from boltrig.api.codex_readiness import (
    codex_release_mode_posture,
    codex_runtime_enabled,
    manifest_requests_codex,
)
from boltrig.config.manifest import FleetManifest

DoctorResult = tuple[str, str, str, str]


def codex_release_check(
    env: Mapping[str, str], production: bool, manifest: FleetManifest
) -> DoctorResult | None:
    release_posture, release_mode = codex_release_mode_posture(env)
    if release_posture == "invalid":
        return (
            "fail",
            "codex_runtime",
            "BOLTRIG_RELEASE_MODE is not an exact admitted release mode.",
            "Set it to exactly core or full; do not add whitespace or change case.",
        )
    if release_posture == "conflict":
        return (
            "fail",
            "codex_runtime",
            "The core release mode conflicts with an enabled trusted Codex lane.",
            "Keep BOLTRIG_CODEX_TRUSTED off for core, or use full after Codex "
            "production admission opens.",
        )
    if release_posture == "disabled":
        return (
            "ok",
            "codex_runtime",
            f"Codex is disabled by the exact {release_mode} release mode.",
            "",
        )
    requested = manifest_requests_codex(manifest) or codex_runtime_enabled(env)
    if not requested:
        return None

    from boltrig.observability.codex_admission import codex_release_posture

    posture = codex_release_posture()
    if posture["status"] == "ready":
        return ("ok", "codex_runtime", "Codex production admission is enabled.", "")
    blockers = len(posture["quarantined_preflight_blockers"])
    return (
        "fail" if production else "warn",
        "codex_runtime",
        f"Codex is development-only: both production gates are closed and "
        f"the preflight retains {blockers} blocker(s).",
        "Do not enable it under a production/staging signal. Complete the governed "
        "preflight evidence, pinned Linux acceptance and fresh production authority first.",
    )


__all__ = ["codex_release_check"]
