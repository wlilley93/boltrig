"""Redacted, execution-neutral Codex rollout and admission evidence."""

from __future__ import annotations

from typing import Any

from boltrig.fleet.infrastructure.codex_agent_runtime import CodexAgentRuntime
from boltrig.fleet.infrastructure.codex_runtime_config import (
    CODEX_RUNTIME_CONFIG_PRODUCTION_READY,
)


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
    runtime_ready = bool(CodexAgentRuntime.production_ready)
    config_ready = bool(CODEX_RUNTIME_CONFIG_PRODUCTION_READY)
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
                if config_ready and runtime_ready
                else "refused_unresolved_isolation_controls"
            ),
            "preflight_evidence": "unavailable_no_durable_cell_receipts",
            "cell_liveness": "unavailable",
        },
        "execution_changed_by_projection": False,
        "sensitive_values_redacted": True,
    }


__all__ = ["codex_admission_projection"]
