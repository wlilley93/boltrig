"""Kernel-owned, scoped and secret-free runtime add-on inventory."""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from boltrig.addons import Addon, AddonRequirement, active_addons, registered

RequirementStatus = Literal[
    "ready", "missing", "degraded", "unavailable", "unverified"
]
RequirementReason = Literal[
    "not_configured",
    "record_missing",
    "not_loaded",
    "health_degraded",
    "health_down",
    "health_unverified",
    "component_missing",
    "credential_missing",
    "evidence_unavailable",
]
RequirementEvidence = Literal[
    "declaration",
    "configuration_presence",
    "credential_reference",
    "cached_adapter_health",
    "stack_status",
]
ConfigurationStatus = Literal[
    "ready", "missing", "degraded", "unavailable", "unverified", "not_required"
]
RuntimeStatus = Literal["ready", "degraded", "unavailable", "unverified", "inactive"]

_REQUIREMENT_STATUSES = frozenset(
    {"ready", "missing", "degraded", "unavailable", "unverified"}
)
_REQUIREMENT_REASONS = frozenset(
    {
        "not_configured",
        "record_missing",
        "not_loaded",
        "health_degraded",
        "health_down",
        "health_unverified",
        "component_missing",
        "credential_missing",
        "evidence_unavailable",
    }
)
_REQUIREMENT_EVIDENCE = frozenset(
    {
        "declaration",
        "configuration_presence",
        "credential_reference",
        "cached_adapter_health",
        "stack_status",
    }
)
_EVIDENCE_BY_KIND: dict[str, RequirementEvidence] = {
    "adapter": "cached_adapter_health",
    "component": "stack_status",
    "environment": "configuration_presence",
    "credential_ref": "credential_reference",
}


@dataclass(frozen=True)
class RequirementObservation:
    id: str
    kind: str
    required: bool
    status: RequirementStatus
    reason: RequirementReason | None
    evidence: RequirementEvidence

    def __post_init__(self) -> None:
        if self.status not in _REQUIREMENT_STATUSES:
            raise ValueError("unknown add-on requirement status")
        if self.reason is not None and self.reason not in _REQUIREMENT_REASONS:
            raise ValueError("unknown add-on requirement reason")
        if self.evidence not in _REQUIREMENT_EVIDENCE:
            raise ValueError("unknown add-on requirement evidence")

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "required": self.required,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def _observed(
    requirement: AddonRequirement,
    status: RequirementStatus,
    reason: RequirementReason | None,
) -> RequirementObservation:
    return RequirementObservation(
        id=requirement.id,
        kind=requirement.kind,
        required=requirement.required,
        status=status,
        reason=reason,
        evidence=_EVIDENCE_BY_KIND[requirement.kind],
    )


async def _adapter_requirement(
    kernel: Any, tenant_id: str, requirement: AddonRequirement
) -> RequirementObservation:
    record = await kernel.store.get_adapter(tenant_id, requirement.ref)
    if record is None:
        return _observed(requirement, "missing", "record_missing")
    if kernel.loader.peek(tenant_id, requirement.ref) is None:
        return _observed(requirement, "unavailable", "not_loaded")
    health = kernel.loader.health_of(tenant_id, requirement.ref)
    if health == "ok":
        return _observed(requirement, "ready", None)
    if health == "degraded":
        return _observed(requirement, "degraded", "health_degraded")
    if health == "down":
        return _observed(requirement, "unavailable", "health_down")
    return _observed(requirement, "unverified", "health_unverified")


async def _component_requirement(
    provider: Any,
    tenant_id: str,
    workspace_id: str | None,
    requirement: AddonRequirement,
) -> RequirementObservation:
    cached = getattr(provider, "cached_snapshot", None)
    if not callable(cached):
        return _observed(requirement, "unavailable", "evidence_unavailable")
    raw = cached(tenant_id=tenant_id, workspace_id=workspace_id)
    if inspect.isawaitable(raw):
        raw = await raw
    if raw is None:
        return _observed(requirement, "unverified", "health_unverified")
    if not isinstance(raw, Mapping):
        return _observed(requirement, "unavailable", "evidence_unavailable")
    components = raw.get("components", [])
    if not isinstance(components, list):
        return _observed(requirement, "unavailable", "evidence_unavailable")
    component = next(
        (
            item
            for item in components
            if isinstance(item, Mapping) and str(item.get("id") or "") == requirement.ref
        ),
        None,
    )
    if component is None:
        return _observed(requirement, "missing", "component_missing")
    status = str(component.get("status") or "unknown").strip().lower()
    if status == "ok":
        return _observed(requirement, "ready", None)
    if status == "degraded":
        return _observed(requirement, "degraded", "health_degraded")
    if status in {"down", "failed", "unavailable"}:
        return _observed(requirement, "unavailable", "health_down")
    return _observed(requirement, "unverified", "health_unverified")


async def _requirement(
    kernel: Any,
    status_provider: Any,
    tenant_id: str,
    workspace_id: str | None,
    requirement: AddonRequirement,
) -> RequirementObservation:
    try:
        if requirement.kind == "adapter":
            return await _adapter_requirement(kernel, tenant_id, requirement)
        if requirement.kind == "component":
            return await _component_requirement(
                status_provider, tenant_id, workspace_id, requirement
            )
        if requirement.kind == "environment":
            present = bool(str(os.environ.get(requirement.ref) or "").strip())
            return _observed(
                requirement,
                "ready" if present else "missing",
                None if present else "not_configured",
            )
        if requirement.kind == "credential_ref":
            present = await kernel.store.has_credential_ref(
                tenant_id, requirement.ref
            )
            return _observed(
                requirement,
                "ready" if present else "missing",
                None if present else "credential_missing",
            )
    except Exception:  # noqa: BLE001 - public state is deliberately keys-only
        return _observed(requirement, "unavailable", "evidence_unavailable")
    return RequirementObservation(
        id=requirement.id,
        kind=requirement.kind,
        required=requirement.required,
        status="unavailable",
        reason="evidence_unavailable",
        evidence="declaration",
    )


def _aggregate(
    observations: list[RequirementObservation],
) -> tuple[ConfigurationStatus, RuntimeStatus, RequirementReason | None]:
    if not observations:
        return "not_required", "ready", None
    missing = next(
        (
            item
            for item in observations
            if item.required and item.status == "missing"
        ),
        None,
    )
    if missing is not None:
        return "missing", "unavailable", missing.reason
    unavailable = next(
        (
            item
            for item in observations
            if item.required and item.status == "unavailable"
        ),
        None,
    )
    if unavailable is not None:
        return "unavailable", "unavailable", unavailable.reason
    unverified = next(
        (
            item
            for item in observations
            if item.required and item.status == "unverified"
        ),
        None,
    )
    if unverified is not None:
        return "unverified", "unverified", unverified.reason
    degraded = next(
        (item for item in observations if item.status == "degraded"),
        None,
    )
    if degraded is not None:
        return "degraded", "degraded", degraded.reason
    return "ready", "ready", None


async def _addon_view(
    kernel: Any,
    status_provider: Any,
    tenant_id: str,
    workspace_id: str | None,
    addon: Addon,
    active_names: frozenset[str],
) -> dict[str, object]:
    observations = [
        await _requirement(
            kernel, status_provider, tenant_id, workspace_id, requirement
        )
        for requirement in addon.requirements
    ]
    configuration, runtime, reason = _aggregate(observations)
    activation = "active" if addon.name in active_names else "inactive"
    if activation == "inactive":
        runtime = "inactive"
        reason = None
    return {
        "id": addon.name,
        "version": addon.version,
        "installation": "installed",
        "activation": activation,
        "contributions": {
            "harness": bool(addon.harness),
            "adapter": addon.adapter_id is not None,
            "consequence_hint": addon.consequence_hint is not None,
        },
        "configuration": {
            "status": configuration,
            "requirements": [item.public() for item in observations],
        },
        "runtime": {"status": runtime, "reason": reason},
    }


async def addon_inventory(
    kernel: Any,
    *,
    tenant_id: str,
    workspace_id: str | None,
    status_provider: Any = None,
) -> dict[str, object]:
    """Project all installed add-ons against the authenticated caller scope."""

    active_names = frozenset(addon.name for addon in active_addons())
    addons = [
        await _addon_view(
            kernel,
            status_provider,
            tenant_id,
            workspace_id,
            addon,
            active_names,
        )
        for addon in registered()
    ]
    return {
        "scope": {"tenant_id": tenant_id, "workspace_id": workspace_id},
        "addons": addons,
    }


__all__ = ["RequirementObservation", "addon_inventory"]
