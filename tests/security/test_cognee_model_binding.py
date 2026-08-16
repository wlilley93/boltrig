"""Cognee reuses the caller's governed chat connection without a second key."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from boltrig.identity.bifrost_user_binding import BifrostUserBinding
from boltrig.memory.cognee_model_binding import (
    CogneeModelBindingResolver,
    CogneeModelUnavailable,
)
from boltrig.models import AiConfig, InvocationContext, Organisation
from boltrig.store import InMemoryStore


@dataclass
class _Gateway:
    binding: BifrostUserBinding
    existing: bool = False
    provider_material: str | None = None

    async def load(self, store, tenant_id, resolution):
        return self.binding if self.existing else None

    async def is_usable(self, binding):
        return True

    async def ensure(self, store, tenant_id, resolution, provider_key):
        self.provider_material = provider_key
        return self.binding


class _Transport:
    def openai_compatible_route(self, virtual_key):
        assert virtual_key == "vk-cognee-scope"
        return (
            "http://bifrost:8080/v1",
            "gateway-inference-secret",
            (("x-bf-vk", virtual_key),),
        )


def _binding() -> BifrostUserBinding:
    return BifrostUserBinding(
        provider="openai",
        model_id="openai/gpt-5.4",
        provider_key_id="provider-key",
        virtual_key_id="virtual-key",
        virtual_key="vk-cognee-scope",
        credential_ref="bifrost-binding",
    )


async def _store(*, include_material: bool = True) -> InMemoryStore:
    store = InMemoryStore()
    await store.create_org(
        Organisation(
            id="tenant-a",
            name="Tenant A",
            slug="tenant-a",
            allow_own_ai_keys=True,
        )
    )
    await store.set_ai_config(
        AiConfig(
            tenant_id="tenant-a",
            level="user",
            scope_id="alice",
            provider="openai",
            model="openai/gpt-5.4",
            credential_ref="chat-provider-key",
        )
    )
    if include_material:
        await store.set_credential_ref(
            "tenant-a",
            "chat-provider-key",
            {"secret": "raw-provider-secret"},
        )
    return store


def _context(tenant_id: str = "tenant-a") -> InvocationContext:
    return InvocationContext(
        tenant_id=tenant_id,
        actor="knowledge-worker",
        actor_tier="ephemeral",
        on_behalf_of="alice",
        workspace_id="workspace-a",
    )


@pytest.mark.security
@pytest.mark.invariant("KNO-05")
async def test_cognee_reuses_scoped_chat_route_without_retaining_provider_key():
    store = await _store()
    gateway = _Gateway(_binding())
    resolver = CogneeModelBindingResolver(
        store,
        gateway=gateway,
        transport=_Transport(),
    )

    route = await resolver.resolve("tenant-a", _context())

    assert route is not None
    assert route.model_id == "openai/gpt-5.4"
    assert route.endpoint == "http://bifrost:8080/v1"
    assert route.extra_headers == (("x-bf-vk", "vk-cognee-scope"),)
    assert gateway.provider_material == "raw-provider-secret"
    assert repr(route) == "CogneeRuntimeModel(redacted=True)"
    assert "raw-provider-secret" not in repr(route)
    assert "vk-cognee-scope" not in repr(route)


@pytest.mark.security
@pytest.mark.invariant("KNO-05")
async def test_existing_bifrost_binding_needs_no_plaintext_resubmission():
    store = await _store(include_material=False)
    gateway = _Gateway(_binding(), existing=True)
    resolver = CogneeModelBindingResolver(
        store,
        gateway=gateway,
        transport=_Transport(),
    )

    assert await resolver.resolve("tenant-a", _context()) is not None
    assert gateway.provider_material is None


@pytest.mark.security
@pytest.mark.invariant("KNO-05")
async def test_cognee_model_resolution_is_tenant_bound_and_default_is_keyless():
    store = await _store()
    resolver = CogneeModelBindingResolver(
        store,
        gateway=_Gateway(_binding()),
        transport=_Transport(),
    )

    with pytest.raises(CogneeModelUnavailable, match="scope is unavailable"):
        await resolver.resolve("tenant-a", _context("tenant-b"))

    empty = InMemoryStore()
    assert await CogneeModelBindingResolver(empty).resolve("tenant-a", _context()) is None
