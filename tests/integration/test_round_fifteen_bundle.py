"""Round Fifteen - bundle loading (FR-EXT-01/02).

A project pins vanilla Boltrig and extends it from a bundle: its own adapter (by
module_ref) and its external MCP servers (mcp.consume), all as DATA, no core edit.
"""

from __future__ import annotations

import tempfile

import pytest

from boltrig.api.bootstrap import _register_consumed_mcp
from boltrig.config import load_manifest
from boltrig.config.manifest import apply_manifest
from boltrig.kernel import Kernel
from boltrig.store import InMemoryStore

T = "acme"

# A bundle manifest: a PROJECT adapter declared by module_ref (a non-builtin id),
# pointing at any importable module exposing build(). We reuse the tickets module
# as the stand-in "project adapter" so the test needs no extra fixture package.
_MANIFEST = """
tenant_id: acme
adapters:
  - id: project-tickets
    module_ref: boltrig.adapters.builtin.memory_tickets:build
"""


@pytest.mark.invariant("FR-EXT-01")
async def test_project_adapter_loads_by_module_ref():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write(_MANIFEST)
        path = fh.name
    manifest = load_manifest(path)
    store = InMemoryStore()
    k = Kernel(store)
    # This extension-contract manifest declares no capabilities; under scoped-
    # declarative reconciliation an empty-capability manifest needs an explicit
    # confirm to clear the mass-deactivation guard.
    await apply_manifest(k, manifest, confirm_bulk_deactivate=True)
    # the project adapter's verbs are registered though its id is not a builtin -
    # the manifest's module_ref was honoured (extend from outside, no core edit).
    assert await store.get_verb(T, "ticket.create") is not None


@pytest.mark.invariant("FR-EXT-02")
async def test_consumed_mcp_servers_register_inert_pending_review():
    store = InMemoryStore()
    k = Kernel(store)
    await _register_consumed_mcp(k, T, {"consume": [
        {"id": "trello-mcp", "url": "http://trello-mcp:9000", "credential_ref": "TRELLO_TOKEN"},
    ]})
    # registered as an adapter...
    rec = await store.get_adapter(T, "trello-mcp")
    assert rec is not None
    # ...but INERT: it exposes no verbs until the review/activate gate runs (SEC-22)
    assert await store.get_verb(T, "trello-mcp") is None
    adapter = await k.loader.get(T, "trello-mcp")
    assert adapter is not None and adapter.activated is False
