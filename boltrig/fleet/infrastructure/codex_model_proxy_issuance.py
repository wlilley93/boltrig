"""Mint a per-cell model bearer for an ALREADY-ATTESTED cell scope (Stage B, 2b).

Ruling [2026] VJS-CC-VJS 1 splits the credential path in two: the unix-socket
ingress SO_PEERCRED-attests the connecting helper into a ``ModelProxyCellScope``
(D1), and THEN a short-TTL, single-cell bearer is minted (D2/D3). This module is
that second half: given an already-attested cell scope, it builds the cell's
grant binding, checks the binding actually belongs to that attested scope (so a
binding-builder bug can never issue a cross-cell bearer), and mints the bearer via
the existing broker.

It performs NO attestation itself - passing a scope here asserts the caller has
already attested it over the unix socket. The low-level socket ingress and the
supervisor's helper registration/spawn wire this up.
"""

from __future__ import annotations

from collections.abc import Callable

from boltrig.fleet.application.model_proxy_grants import (
    DEFAULT_MODEL_PROXY_TTL_SECONDS,
    PhaseScopedModelProxyGrantBroker,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyCellScope,
    ModelProxyGrantBinding,
)

# Build the full grant binding (cell + model + budget) for an attested cell. The
# cell scope comes from attestation; the model/budget bindings come from the
# cell's admission and the read-only budget policy (supplied by the composition).
CellBindingBuilder = Callable[[ModelProxyCellScope], ModelProxyGrantBinding]


async def issue_cell_bearer(
    cell_scope: ModelProxyCellScope,
    *,
    broker: PhaseScopedModelProxyGrantBroker,
    binding_for_cell: CellBindingBuilder,
    startup_request_id: str,
    generation: int,
    ttl_seconds: int = DEFAULT_MODEL_PROXY_TTL_SECONDS,
) -> str:
    """Mint and reveal the raw bearer for an attested ``cell_scope`` (D2/D3).

    Raises ``ValueError`` if the built binding does not belong to the attested
    scope - a hard guard against a binding-builder issuing a bearer bound to any
    other cell than the one that was actually attested at the socket.
    """
    if type(cell_scope) is not ModelProxyCellScope:
        raise TypeError("cell_scope must be an exact ModelProxyCellScope")
    binding = binding_for_cell(cell_scope)
    if type(binding) is not ModelProxyGrantBinding or binding.cell != cell_scope:
        raise ValueError("binding cell does not match the attested cell scope")
    issued = await broker.issue(
        startup_request_id, binding, ttl_seconds=ttl_seconds, generation=generation
    )
    return issued.bearer.reveal()


__all__ = ["CellBindingBuilder", "issue_cell_bearer"]
