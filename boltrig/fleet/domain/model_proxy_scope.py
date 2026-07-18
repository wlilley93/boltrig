"""Exact process, model, budget, and trusted-observation values for model grants."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re

from boltrig.models import RunId, TenantId, WorkspaceId

MAX_MODEL_PROXY_IDENTIFIER_CHARS = 160
MAX_SIGNED_BIGINT = 2**63 - 1
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}\Z")
_PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if len(value) > MAX_MODEL_PROXY_IDENTIFIER_CHARS or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded safe ASCII identifier")
    return value


def _positive(label: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    if not 1 <= value <= MAX_SIGNED_BIGINT:
        raise ValueError(f"{label} must be positive and fit a signed BIGINT")
    return value


def _nonnegative(label: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an exact integer")
    if not 0 <= value <= MAX_SIGNED_BIGINT:
        raise ValueError(f"{label} must be non-negative and fit a signed BIGINT")
    return value


def _policy_digest(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _PREFIXED_SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase prefixed SHA-256 digest")
    return value


class ModelProxyRequestProvenance(str, Enum):
    KERNEL_PEER_AND_SERVER_REQUEST = "kernel_peer_and_server_request"


@dataclass(frozen=True, order=True)
class ModelProxyRootScope:
    tenant_id: TenantId
    workspace_id: WorkspaceId
    root_run_id: RunId

    def __post_init__(self) -> None:
        _identifier("tenant_id", self.tenant_id)
        _identifier("workspace_id", self.workspace_id)
        _identifier("root_run_id", self.root_run_id)


@dataclass(frozen=True, order=True)
class ModelProxyPhaseScope:
    root: ModelProxyRootScope
    phase_id: str

    def __post_init__(self) -> None:
        if type(self.root) is not ModelProxyRootScope:
            raise TypeError("root must be an exact ModelProxyRootScope")
        _identifier("phase_id", self.phase_id)


@dataclass(frozen=True, order=True)
class ModelProxyAssignmentScope:
    phase: ModelProxyPhaseScope
    assignment_id: str

    def __post_init__(self) -> None:
        if type(self.phase) is not ModelProxyPhaseScope:
            raise TypeError("phase must be an exact ModelProxyPhaseScope")
        _identifier("assignment_id", self.assignment_id)


@dataclass(frozen=True, order=True)
class ModelProxyCellScope:
    """Exact Linux process identity captured from the proxy's kernel peer."""

    assignment: ModelProxyAssignmentScope
    cell_id: str
    pid: int
    pid_start_ticks: int
    boot_id: str
    pid_namespace_inode: int
    cgroup_identity_digest: str

    def __post_init__(self) -> None:
        if type(self.assignment) is not ModelProxyAssignmentScope:
            raise TypeError("assignment must be an exact ModelProxyAssignmentScope")
        _identifier("cell_id", self.cell_id)
        _positive("pid", self.pid)
        _positive("pid_start_ticks", self.pid_start_ticks)
        _identifier("boot_id", self.boot_id)
        _positive("pid_namespace_inode", self.pid_namespace_inode)
        _policy_digest("cgroup identity digest", self.cgroup_identity_digest)


@dataclass(frozen=True, order=True)
class ModelProxyModelBinding:
    model_id: str
    policy_digest: str

    def __post_init__(self) -> None:
        _identifier("model_id", self.model_id)
        _policy_digest("model policy digest", self.policy_digest)


@dataclass(frozen=True, order=True)
class ModelProxyBudgetBinding:
    budget_id: str
    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int
    max_cost_micros: int
    policy_digest: str

    def __post_init__(self) -> None:
        _identifier("budget_id", self.budget_id)
        input_limit = _positive("max_input_tokens", self.max_input_tokens)
        output_limit = _positive("max_output_tokens", self.max_output_tokens)
        total_limit = _positive("max_total_tokens", self.max_total_tokens)
        _nonnegative("max_cost_micros", self.max_cost_micros)
        if max(input_limit, output_limit) > total_limit:
            raise ValueError("input and output token limits must fit the total token limit")
        _policy_digest("budget policy digest", self.policy_digest)


@dataclass(frozen=True, order=True)
class ModelProxyGrantBinding:
    cell: ModelProxyCellScope
    model: ModelProxyModelBinding
    budget: ModelProxyBudgetBinding

    def __post_init__(self) -> None:
        if type(self.cell) is not ModelProxyCellScope:
            raise TypeError("cell must be an exact ModelProxyCellScope")
        if type(self.model) is not ModelProxyModelBinding:
            raise TypeError("model must be an exact ModelProxyModelBinding")
        if type(self.budget) is not ModelProxyBudgetBinding:
            raise TypeError("budget must be an exact ModelProxyBudgetBinding")


@dataclass(frozen=True)
class TrustedModelProxyRequestObservation:
    """Internal-only kernel peer plus server-parsed model and budget.

    Production authentication stays off until Unix-socket ingress creates this
    from SO_PEERCRED, proc start ticks, boot/namespace/cgroup identity, and its
    own parsed request. Caller JSON is never acceptable provenance.
    """

    cell: ModelProxyCellScope
    model: ModelProxyModelBinding
    budget: ModelProxyBudgetBinding
    provenance: ModelProxyRequestProvenance = field(
        default=ModelProxyRequestProvenance.KERNEL_PEER_AND_SERVER_REQUEST,
        init=False,
    )

    def __post_init__(self) -> None:
        if type(self.cell) is not ModelProxyCellScope:
            raise TypeError("cell must be an exact ModelProxyCellScope")
        if type(self.model) is not ModelProxyModelBinding:
            raise TypeError("model must be an exact ModelProxyModelBinding")
        if type(self.budget) is not ModelProxyBudgetBinding:
            raise TypeError("budget must be an exact ModelProxyBudgetBinding")

    @property
    def binding(self) -> ModelProxyGrantBinding:
        return ModelProxyGrantBinding(self.cell, self.model, self.budget)


def model_proxy_startup_digest(binding: ModelProxyGrantBinding, request_id: str) -> str:
    if type(binding) is not ModelProxyGrantBinding:
        raise TypeError("binding must be an exact ModelProxyGrantBinding")
    safe_request_id = _identifier("startup_request_id", request_id)
    cell = binding.cell
    assignment = cell.assignment
    root = assignment.phase.root
    budget = binding.budget
    material = (
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        assignment.phase.phase_id,
        assignment.assignment_id,
        cell.cell_id,
        cell.pid,
        cell.pid_start_ticks,
        cell.boot_id,
        cell.pid_namespace_inode,
        cell.cgroup_identity_digest,
        binding.model.model_id,
        binding.model.policy_digest,
        budget.budget_id,
        budget.max_input_tokens,
        budget.max_output_tokens,
        budget.max_total_tokens,
        budget.max_cost_micros,
        budget.policy_digest,
        safe_request_id,
    )
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MAX_SIGNED_BIGINT",
    "ModelProxyAssignmentScope",
    "ModelProxyBudgetBinding",
    "ModelProxyCellScope",
    "ModelProxyGrantBinding",
    "ModelProxyModelBinding",
    "ModelProxyPhaseScope",
    "ModelProxyRequestProvenance",
    "ModelProxyRootScope",
    "TrustedModelProxyRequestObservation",
    "model_proxy_startup_digest",
]
