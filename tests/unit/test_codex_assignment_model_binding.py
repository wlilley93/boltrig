"""Exact, bounded runtime-to-admission model hand-off."""

from __future__ import annotations

import pytest

from boltrig.fleet.infrastructure.codex_assignment_model_binding import (
    MAX_CODEX_ASSIGNMENT_MODEL_BINDINGS,
    CodexAssignmentModelBinding,
    CodexAssignmentModelBindingError,
    CodexAssignmentModelBindingRegistry,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    CodexRuntimeAdmissionError,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
    TrustedProxyCodexPhaseCellProvider,
)
from tests.unit.codex_runtime_fakes import assignment


def _binding(suffix: str, model: str = "openai/gpt-5.4-codex"):
    exact_assignment = assignment(suffix)
    return CodexAssignmentModelBinding(
        assignment=exact_assignment,
        tenant_id=exact_assignment.phase.principal.tenant_id,
        endpoint_id=f"choice-{suffix}",
        model_id=model,
    )


def test_registry_is_pop_once_and_keyed_by_the_full_assignment() -> None:
    registry = CodexAssignmentModelBindingRegistry()
    first = _binding("one", "provider/model-one")
    second = _binding("two", "provider/model-two")
    registry.register(first)
    registry.register(second)

    assert registry.take(second.assignment) == second
    assert registry.take(second.assignment) is None
    assert registry.take(first.assignment) == first
    assert len(registry) == 0


def test_registry_refuses_duplicate_and_over_capacity() -> None:
    duplicate = _binding("duplicate")
    registry = CodexAssignmentModelBindingRegistry()
    registry.register(duplicate)
    with pytest.raises(CodexAssignmentModelBindingError, match="already registered"):
        registry.register(duplicate)

    bounded = CodexAssignmentModelBindingRegistry()
    for index in range(MAX_CODEX_ASSIGNMENT_MODEL_BINDINGS):
        bounded.register(_binding(f"bounded-{index}"))
    with pytest.raises(CodexAssignmentModelBindingError, match="registry is full"):
        bounded.register(_binding("overflow"))


def test_binding_refuses_cross_tenant_or_mutable_model_alias() -> None:
    exact_assignment = assignment("tenant")
    with pytest.raises(CodexAssignmentModelBindingError, match="tenant"):
        CodexAssignmentModelBinding(
            assignment=exact_assignment,
            tenant_id="another-tenant",
            model_id="provider/model",
        )
    with pytest.raises(CodexAssignmentModelBindingError, match="path"):
        CodexAssignmentModelBinding(
            assignment=exact_assignment,
            tenant_id=exact_assignment.phase.principal.tenant_id,
            model_id="provider//latest",
        )
    with pytest.raises(CodexAssignmentModelBindingError, match="URL-safe"):
        CodexAssignmentModelBinding(
            assignment=exact_assignment,
            tenant_id=exact_assignment.phase.principal.tenant_id,
            endpoint_id="unsafe/path",
            model_id="provider/model-20260812",
        )


def test_discard_is_idempotent() -> None:
    registry = CodexAssignmentModelBindingRegistry()
    value = _binding("discard")
    registry.register(value)
    registry.discard(value.assignment)
    registry.discard(value.assignment)
    assert registry.take(value.assignment) is None


@pytest.mark.invariant("SEC-WRK-02")
def test_trusted_provider_requires_and_pop_once_consumes_the_exact_binding() -> None:
    provider = object.__new__(TrustedProxyCodexPhaseCellProvider)
    provider._model_bindings = CodexAssignmentModelBindingRegistry()
    selected = _binding("provider", "provider/model-selected-20260812")

    with pytest.raises(CodexRuntimeAdmissionError, match="no resolved model"):
        provider._take_model_binding(selected.assignment)

    provider._model_bindings.register(selected)
    assert provider._take_model_binding(selected.assignment) == selected
    with pytest.raises(CodexRuntimeAdmissionError, match="no resolved model"):
        provider._take_model_binding(selected.assignment)
