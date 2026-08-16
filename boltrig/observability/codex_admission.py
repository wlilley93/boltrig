"""Redacted, execution-neutral Codex rollout and admission evidence."""

from __future__ import annotations

from typing import Any

from boltrig.fleet.infrastructure.codex_agent_runtime import CodexAgentRuntime
from boltrig.fleet.infrastructure.codex_runtime_config import (
    CODEX_RUNTIME_CONFIG_PRODUCTION_READY,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    QUARANTINED_PREFLIGHT_BLOCKERS,
)


def codex_release_posture() -> dict[str, Any]:
    """Return the static, redacted gate that controls production admission.

    This deliberately does not probe a cell or turn local observations into
    authority.  The two constants are necessary release gates; the blocker
    names describe why they are not sufficient while the only available
    preflight receipt remains quarantined.  Keeping this in one projection
    prevents doctor, readiness and Worker status from giving three different
    answers about the same build.
    """

    runtime_ready = bool(CodexAgentRuntime.production_ready)
    config_ready = bool(CODEX_RUNTIME_CONFIG_PRODUCTION_READY)
    blockers = tuple(QUARANTINED_PREFLIGHT_BLOCKERS)
    # A two-line constant flip must never turn a quarantined receipt into a
    # production attestation.  The authority-backed production change must
    # replace this projection's receipt source as well as opening both gates.
    ready = runtime_ready and config_ready and not blockers
    return {
        "status": "ready" if ready else "blocked",
        "reason": None if ready else "production_gate_closed",
        "runtime_class_production_ready": runtime_ready,
        "runtime_config_production_ready": config_ready,
        "quarantined_preflight_blockers": list(blockers),
        "fresh_authority_required": not ready,
        "sensitive_values_redacted": True,
    }


def codex_admission_projection(
    execution_stack: Any,
    *,
    trusted_provider_configured: bool,
) -> dict[str, Any]:
    """Describe the effective OFF wall without probing or admitting a cell."""

    generation = getattr(execution_stack, "policy_generation", None)
    if type(generation) is not int or not 1 <= generation <= 2_147_483_647:
        generation = None
    scaffold_composed = generation is not None
    release = codex_release_posture()
    runtime_ready = bool(release["runtime_class_production_ready"])
    config_ready = bool(release["runtime_config_production_ready"])
    return {
        "status": "available",
        "evidence_kind": "process_composition_not_runtime_liveness",
        "rollout": {
            "policy_source": (
                "immutable_off_scaffold"
                if scaffold_composed
                else "scaffold_not_composed"
            ),
            "mode": "off",
            "generation": generation,
            "shadow_root_decisions": (
                "active_execution_neutral"
                if scaffold_composed
                else "disabled"
            ),
            "root_execution": "legacy_only",
            "assignment_admission": "inactive_never_called",
            "canary_decision": "unavailable_rollout_off",
        },
        "runtime": {
            "trusted_provider": (
                "configured_development_only"
                if trusted_provider_configured
                else "off"
            ),
            "runtime_config_production_ready": config_ready,
            "runtime_class_production_ready": runtime_ready,
            "production_activation": (
                "available"
                if release["status"] == "ready"
                else "refused_unresolved_isolation_controls"
            ),
            "preflight_evidence": "unavailable_no_durable_cell_receipts",
            "cell_liveness": "unavailable",
        },
        "execution_changed_by_projection": False,
        "release_posture": release,
        "sensitive_values_redacted": True,
    }


__all__ = ["codex_admission_projection", "codex_release_posture"]
