"""Shared fixtures. The kernel runs on the in-memory store - no external services."""

from __future__ import annotations

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.kernel import Kernel
from nankle.models import GrantSet, InvocationContext, TenantPermissions
from nankle.store import InMemoryStore

TENANT = "acme"


def make_ctx(grants: list[str], *, run_id: str = "run-1", depth: int = 0, **kw) -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(grants),
        actor=kw.get("actor", "ephemeral-1"),
        actor_tier=kw.get("actor_tier", "ephemeral"),
        run_id=run_id,
        parent_run_id=kw.get("parent_run_id"),
        depth=depth,
        on_behalf_of=kw.get("on_behalf_of"),
        skills_loaded=tuple(kw.get("skills_loaded", ())),
    )


async def _build_kernel(*, blocking_verbs: set[str] | None = None) -> tuple[Kernel, object]:
    store = InMemoryStore()
    # tenant ceiling permits the whole ticket noun (role-derived in production)
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["ticket.*"])))
    kernel = Kernel(store, blocking_verbs=blocking_verbs or set())
    adapter = build_tickets()
    await kernel.register_adapter(TENANT, adapter)
    return kernel, adapter


@pytest.fixture
async def kernel():
    k, _ = await _build_kernel()
    return k


@pytest.fixture
async def kernel_and_adapter():
    return await _build_kernel()


@pytest.fixture
async def gated_kernel():
    """A kernel where ticket.create is a blocking (gated) verb."""
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    return k
