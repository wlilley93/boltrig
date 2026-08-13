"""Immutable quarantined Codex pre-thread receipt and fixed blockers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from boltrig.fleet.domain.skill_attestation import SkillAttestation

from .codex_binary_pin import CODEX_CLI_VERSION
from .codex_runtime_surface_evidence import (
    QuarantinedCodexSurfaceEvidence,
    optional_surface_evidence_digest,
    validate_optional_surface_evidence,
)

CODEX_PROTOCOL_BUNDLE_DIGEST = (
    "sha256:0194f4370fd6ec268f81270217b56b2d1133ecc2c2a1560f3870dd6ec16e9810"
)
QUARANTINED_PREFLIGHT_BLOCKERS = (
    "effective_apps",
    "effective_config",
    "effective_external_agents",
    "effective_plugins",
    "effective_provider",
    "effective_tools",
    "full_generated_schema_contract",
)


class CodexRuntimeAdmissionError(PermissionError):
    """A phase was not admitted to the exact quarantined read-only cell."""


def _document_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "ascii"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class QuarantinedCodexPreflightReceipt:
    """Incomplete evidence from the probes safe to run before ``thread/start``."""

    skill_attestation: SkillAttestation
    surface_evidence: QuarantinedCodexSurfaceEvidence | None = None
    observed_mcp_server_count: int = 0
    observed_hook_count: int = 0
    protocol_version: str = CODEX_CLI_VERSION
    protocol_bundle_digest: str = CODEX_PROTOCOL_BUNDLE_DIGEST
    production_blockers: tuple[str, ...] = QUARANTINED_PREFLIGHT_BLOCKERS

    def __post_init__(self) -> None:
        if type(self.skill_attestation) is not SkillAttestation:
            raise TypeError("skill_attestation must be an exact SkillAttestation")
        validate_optional_surface_evidence(self.surface_evidence)
        if (
            type(self.observed_mcp_server_count) is not int
            or type(self.observed_hook_count) is not int
            or not 0 <= self.observed_mcp_server_count <= 1
            or self.observed_hook_count != 0
        ):
            raise CodexRuntimeAdmissionError("quarantined external inventory must be empty")
        if self.protocol_version != CODEX_CLI_VERSION:
            raise CodexRuntimeAdmissionError("quarantined receipt uses another protocol")
        if self.protocol_bundle_digest != CODEX_PROTOCOL_BUNDLE_DIGEST:
            raise CodexRuntimeAdmissionError("quarantined receipt uses another schema bundle")
        if self.production_blockers != QUARANTINED_PREFLIGHT_BLOCKERS:
            raise CodexRuntimeAdmissionError("quarantined receipt omitted a production blocker")

    @property
    def production_complete(self) -> bool:
        return False

    def digest(self) -> str:
        return _document_digest(
            {
                "observed_hook_count": self.observed_hook_count,
                "observed_mcp_server_count": self.observed_mcp_server_count,
                "production_blockers": self.production_blockers,
                "production_complete": False,
                "protocol_bundle_digest": self.protocol_bundle_digest,
                "protocol_version": self.protocol_version,
                "skill_attestation": self.skill_attestation.digest,
                "surface_evidence": optional_surface_evidence_digest(self.surface_evidence),
            }
        )


__all__ = [
    "CODEX_PROTOCOL_BUNDLE_DIGEST",
    "QUARANTINED_PREFLIGHT_BLOCKERS",
    "CodexRuntimeAdmissionError",
    "QuarantinedCodexPreflightReceipt",
]
