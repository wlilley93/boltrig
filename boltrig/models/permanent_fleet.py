"""Typed desired/observed state for the permanent fleet hierarchy.

AgentCapability rows are selectable runtime profiles, not proof that a Chief of
Staff or department head exists in a running worker.  This contract keeps the
authored hierarchy and worker observation separate so browser surfaces cannot
infer liveness from ``is_ephemeral=False``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re

from .base import TenantId


@dataclass
class PermanentFleetObservation:
    tenant_id: TenantId
    worker_id: str
    generation: str
    status: str  # applied | degraded
    apply_mode: str = "startup_snapshot"
    applied_fields: list[str] = field(default_factory=list)
    inactive_fields: list[str] = field(default_factory=list)
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not str(self.tenant_id).strip():
            raise ValueError("tenant_id is required")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", self.worker_id):
            raise ValueError("worker_id is invalid")
        if not re.fullmatch(r"pf_[a-f0-9]{24}", self.generation):
            raise ValueError("permanent fleet generation is invalid")
        if self.status not in {"applied", "degraded"}:
            raise ValueError("permanent fleet observation status is invalid")
        if self.apply_mode != "startup_snapshot":
            raise ValueError("permanent fleet apply mode is invalid")
        allowed = {
            "department_routing_identity",
            "department_supported_skills",
            "chief_routing_identity",
            "chief_supported_skills",
            "purpose",
            "brief",
            "runtime",
            "model_endpoint",
            "max_depth",
            "cost_tier",
        }
        for label, values in (
            ("applied_fields", self.applied_fields),
            ("inactive_fields", self.inactive_fields),
        ):
            if (
                not isinstance(values, list)
                or len(values) != len(set(values))
                or not set(values) <= allowed
            ):
                raise ValueError(f"{label} is invalid")
        if set(self.applied_fields) & set(self.inactive_fields):
            raise ValueError("applied and inactive fields must be disjoint")
