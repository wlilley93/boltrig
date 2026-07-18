"""Tests for the mint-from-attested-scope seam (Stage B, 2b).

Ruling [2026] VJS-CC-VJS 1 splits issuance in two: the unix-socket ingress
SO_PEERCRED-attests the helper into a cell scope (D1), then a short-TTL bearer is
minted for exactly that scope (D2/D3). This pins the second half: the minted
bearer verifies for the attested cell, and a binding-builder that returns a
DIFFERENT cell (or a non-binding) is rejected before any grant is stored - a
cross-cell bearer can never be issued.
"""

from __future__ import annotations

from typing import Any

import pytest

from boltrig.fleet.application.model_proxy_grants import (
    PhaseScopedModelProxyGrantBroker,
)
from boltrig.fleet.domain.model_proxy_scope import ModelProxyGrantBinding
from boltrig.fleet.infrastructure.codex_model_proxy_issuance import issue_cell_bearer
from boltrig.fleet.infrastructure.codex_model_proxy_server import store_bearer_verifier
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
    MemoryModelProxyGrantStore,
)
from tests.unit.test_model_proxy_grants import _binding


def _fixed_builder(binding: ModelProxyGrantBinding) -> Any:
    def build(cell: Any) -> ModelProxyGrantBinding:
        return binding

    return build


async def test_issues_a_bearer_that_verifies_for_the_attested_cell() -> None:
    store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(store)
    binding = _binding()

    bearer = await issue_cell_bearer(
        binding.cell,
        broker=broker,
        binding_for_cell=_fixed_builder(binding),
        startup_request_id="startup-req-1",
        generation=1,
    )

    verify = store_bearer_verifier(store, generation=1)
    assert await verify(bearer) is True


async def test_binding_for_another_cell_is_rejected_before_issuance() -> None:
    store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(store)
    attested = _binding(cell="cell-attested")
    # The builder returns a binding for a DIFFERENT cell than the attested one.
    other = _binding(cell="cell-other")

    with pytest.raises(ValueError, match="does not match the attested cell scope"):
        await issue_cell_bearer(
            attested.cell,
            broker=broker,
            binding_for_cell=_fixed_builder(other),
            startup_request_id="startup-req-2",
            generation=1,
        )
    # nothing was minted: a bearer for neither cell verifies
    verify = store_bearer_verifier(store, generation=1)
    assert await verify("any-bearer") is False


async def test_a_non_binding_from_the_builder_is_rejected() -> None:
    store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(store)
    binding = _binding()

    def bad_builder(cell: Any) -> Any:
        return "not-a-binding"

    with pytest.raises(ValueError):
        await issue_cell_bearer(
            binding.cell,
            broker=broker,
            binding_for_cell=bad_builder,
            startup_request_id="startup-req-3",
            generation=1,
        )


async def test_a_non_cell_scope_is_rejected() -> None:
    store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(store)

    with pytest.raises(TypeError, match="exact ModelProxyCellScope"):
        await issue_cell_bearer(
            "not-a-cell-scope",  # type: ignore[arg-type]
            broker=broker,
            binding_for_cell=_fixed_builder(_binding()),
            startup_request_id="startup-req-4",
            generation=1,
        )
