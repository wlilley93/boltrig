"""Pop-once hand-off of one exact model selection to trusted Codex admission.

The runtime resolver owns tenant-scoped endpoint lookup.  The trusted provider
owns cell admission.  This bounded registry carries only the immutable result of
that lookup across the seam, keyed by the full phase assignment so concurrent
tenants or runs cannot consume one another's selection.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from boltrig.fleet.domain import ExactModelPolicy, PhaseAssignmentRef, ReasoningEffort
from boltrig.model_choice_policy import opaque_model_choice_id

MAX_CODEX_ASSIGNMENT_MODEL_BINDINGS = 64


class CodexAssignmentModelBindingError(ValueError):
    """A model binding or registry operation failed closed validation."""


@dataclass(frozen=True, repr=False, slots=True)
class CodexAssignmentModelBinding:
    """One server-resolved model snapshot for one exact Codex assignment."""

    assignment: PhaseAssignmentRef
    tenant_id: str
    model_id: str
    endpoint_id: str | None = None
    gateway_virtual_key: str | None = None

    def __post_init__(self) -> None:
        if type(self.assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        if (
            type(self.tenant_id) is not str
            or not self.tenant_id
            or self.tenant_id != self.tenant_id.strip()
            or self.tenant_id != self.assignment.phase.principal.tenant_id
        ):
            raise CodexAssignmentModelBindingError(
                "model binding tenant does not match the assignment"
            )
        try:
            policy = ExactModelPolicy(self.model_id, ReasoningEffort.HIGH)
        except (TypeError, ValueError) as error:
            raise CodexAssignmentModelBindingError(str(error)) from None
        object.__setattr__(self, "model_id", policy.model_id)
        if self.endpoint_id is not None:
            try:
                opaque_model_choice_id(self.endpoint_id)
            except ValueError as error:
                raise CodexAssignmentModelBindingError(str(error)) from None
        if self.gateway_virtual_key is not None and (
            type(self.gateway_virtual_key) is not str
            or not self.gateway_virtual_key
            or len(self.gateway_virtual_key) > 8192
            or any(
                ord(character) < 0x21 or ord(character) > 0x7E
                for character in self.gateway_virtual_key
            )
        ):
            raise CodexAssignmentModelBindingError(
                "gateway virtual key must be bounded printable ASCII"
            )

    def __repr__(self) -> str:
        return "CodexAssignmentModelBinding(redacted=True)"


class CodexAssignmentModelBindingRegistry:
    """Thread-safe, bounded and pop-once assignment/model hand-off."""

    def __init__(self) -> None:
        self._bindings: dict[PhaseAssignmentRef, CodexAssignmentModelBinding] = {}
        self._lock = threading.Lock()

    def register(self, binding: CodexAssignmentModelBinding) -> None:
        if type(binding) is not CodexAssignmentModelBinding:
            raise TypeError("binding must be an exact CodexAssignmentModelBinding")
        with self._lock:
            if binding.assignment in self._bindings:
                raise CodexAssignmentModelBindingError(
                    "assignment model binding already registered"
                )
            if len(self._bindings) >= MAX_CODEX_ASSIGNMENT_MODEL_BINDINGS:
                raise CodexAssignmentModelBindingError(
                    "assignment model binding registry is full"
                )
            self._bindings[binding.assignment] = binding

    def take(
        self, assignment: PhaseAssignmentRef
    ) -> CodexAssignmentModelBinding | None:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        with self._lock:
            return self._bindings.pop(assignment, None)

    def discard(self, assignment: object) -> None:
        if type(assignment) is PhaseAssignmentRef:
            with self._lock:
                self._bindings.pop(assignment, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._bindings)


__all__ = [
    "MAX_CODEX_ASSIGNMENT_MODEL_BINDINGS",
    "CodexAssignmentModelBinding",
    "CodexAssignmentModelBindingError",
    "CodexAssignmentModelBindingRegistry",
]
