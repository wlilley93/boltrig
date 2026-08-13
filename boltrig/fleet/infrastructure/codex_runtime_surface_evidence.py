"""Bounded pre-thread evidence for Codex surfaces that 0.144.3 can expose.

This evidence is deliberately quarantined.  It records observations that can be
made before ``thread/start`` and binds them into the admitted-cell digest, but it
does not claim provider identity or a complete running schema contract.  Those
two upstream gaps keep production admission closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


def _require_digest(label: str, value: object) -> str:
    if type(value) is not str or not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{label} must be a prefixed SHA-256 digest")
    try:
        bytes.fromhex(value[7:])
    except ValueError:
        raise ValueError(f"{label} must be a prefixed SHA-256 digest") from None
    return value


def canonical_surface_digest(value: object) -> str:
    """Digest one JSON-safe, already validated surface observation."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class QuarantinedCodexSurfaceEvidence:
    """Exact observations that remain insufficient for production admission."""

    effective_config_digest: str
    composed_config_digest: str
    apps_inventory_digest: str
    plugins_inventory_digest: str
    external_agents_inventory_digest: str
    effective_tools_digest: str
    observed_app_count: int = 0
    observed_plugin_count: int = 0
    observed_external_agent_count: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("effective config digest", self.effective_config_digest),
            ("composed config digest", self.composed_config_digest),
            ("apps inventory digest", self.apps_inventory_digest),
            ("plugins inventory digest", self.plugins_inventory_digest),
            ("external agents inventory digest", self.external_agents_inventory_digest),
            ("effective tools digest", self.effective_tools_digest),
        ):
            _require_digest(label, value)
        counts = (
            self.observed_app_count,
            self.observed_plugin_count,
            self.observed_external_agent_count,
        )
        if any(type(value) is not int or value != 0 for value in counts):
            raise ValueError("quarantined Codex surface inventories must be empty")

    @property
    def production_complete(self) -> bool:
        return False

    def digest(self) -> str:
        return canonical_surface_digest(
            {
                "apps_inventory_digest": self.apps_inventory_digest,
                "composed_config_digest": self.composed_config_digest,
                "effective_config_digest": self.effective_config_digest,
                "effective_tools_digest": self.effective_tools_digest,
                "external_agents_inventory_digest": self.external_agents_inventory_digest,
                "observed_app_count": self.observed_app_count,
                "observed_external_agent_count": self.observed_external_agent_count,
                "observed_plugin_count": self.observed_plugin_count,
                "plugins_inventory_digest": self.plugins_inventory_digest,
                "production_complete": False,
            }
        )


def validate_optional_surface_evidence(value: object) -> None:
    if value is not None and type(value) is not QuarantinedCodexSurfaceEvidence:
        raise TypeError("surface_evidence must be exact quarantined evidence or None")


def optional_surface_evidence_digest(value: QuarantinedCodexSurfaceEvidence | None) -> str | None:
    return None if value is None else value.digest()


def surface_tools_match(
    evidence: QuarantinedCodexSurfaceEvidence,
    expected_tools: tuple[str, ...],
) -> bool:
    return evidence.effective_tools_digest == canonical_surface_digest(
        tuple(sorted(expected_tools))
    )


__all__ = [
    "QuarantinedCodexSurfaceEvidence",
    "canonical_surface_digest",
    "optional_surface_evidence_digest",
    "surface_tools_match",
    "validate_optional_surface_evidence",
]
