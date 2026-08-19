"""Curated mapping packs, and the dormancy that lets one image serve both boxes.

SPEC §5 level 2. A pack is a curator's claim about somebody else's API, shipped
as versioned data, and it is the mechanism behind "the Opbox capabilities ship
inside Boltrig but stay dormant until Opbox is present".
"""

from __future__ import annotations

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.capabilities.mapping_packs import (
    MappingPackError,
    load_packs,
    parse_pack,
)
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "acme"


class _Door:
    runtime = "script"
    source = "generated"

    def __init__(self, adapter_id: str, verbs: tuple[str, ...]) -> None:
        self.id = adapter_id
        self.version = "1.0.0"
        self._verbs = verbs

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id=verb,
                noun_id=verb.split(".")[-1],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                description=verb,
            )
            for verb in self._verbs
        ]

    async def execute(self, verb, params, credential, context) -> Result:
        return Result.success({"verb": verb})


async def _register(adapter) -> InMemoryStore:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["*"])))
    await Kernel(store, blocking_verbs=set()).register_adapter(TENANT, adapter)
    return store


# ---------------------------------------------------------------- the pack file


def test_the_shipped_opbox_pack_parses_and_maps_only_opbox():
    pack = load_packs()["opbox"]
    assert pack.provider == "opbox"
    assert all(m.operation_id.startswith("opbox.") for m in pack.mappings)


def test_every_shipped_mapping_pins_a_capability_version():
    for pack in load_packs().values():
        assert all(m.capability_version >= 1 for m in pack.mappings)


def test_an_unpinned_mapping_is_refused():
    """Unpinned means "the tenant's newest live version".

    A pack that did not pin would silently re-target itself when a new
    capability version appeared, making a curated claim about a contract it has
    never seen.
    """
    with pytest.raises(MappingPackError, match="pin a capability version"):
        parse_pack(
            {
                "pack": "p",
                "version": 1,
                "provider": "x",
                "mappings": [{"operation": "x.a", "implements": "thing.get"}],
            }
        )


def test_a_pack_mapping_one_operation_twice_is_refused():
    with pytest.raises(MappingPackError, match="mapped twice"):
        parse_pack(
            {
                "pack": "p",
                "version": 1,
                "provider": "x",
                "mappings": [
                    {"operation": "x.a", "implements": "thing.get@1"},
                    {"operation": "x.a", "implements": "other.get@1"},
                ],
            }
        )


def test_a_pack_with_no_mappings_is_refused():
    with pytest.raises(MappingPackError):
        parse_pack({"pack": "p", "version": 1, "provider": "x", "mappings": []})


# ------------------------------------------------------------------ application


@pytest.mark.asyncio
async def test_a_pack_binds_a_provider_that_declares_nothing():
    store = await _register(_Door("opbox", ("opbox.create_matter", "opbox.get_matter")))

    opened = await store.list_capability_bindings(TENANT, "matter.open")

    assert [b.source_operation_id for b in opened] == ["opbox.create_matter"]
    assert opened[0].created_from == "mapping_pack"


@pytest.mark.asyncio
async def test_a_pack_binding_is_never_eligible_until_someone_approves_it():
    """A curator's data file is evidence, not authority.

    ``proposed`` keeps it out of every route, so a pack cannot publish a
    model-callable verb on its own.
    """
    store = await _register(_Door("opbox", ("opbox.create_matter",)))

    binding = (await store.list_capability_bindings(TENANT, "matter.open"))[0]

    assert binding.status == "proposed"


@pytest.mark.asyncio
async def test_the_pack_is_dormant_where_its_provider_is_absent():
    """THE PROPERTY THAT LETS ONE IMAGE SERVE BOTH BOXES.

    The Opbox pack ships in every Boltrig. On a box with no Opbox door it must
    bind nothing at all - not a disabled binding, not a proposed one, nothing.

    THE OPERATION NAMES HERE ARE OPBOX'S ON PURPOSE. The first version of this
    test registered a hubspot door exposing `hubspot.create_deal`, and it
    passed even with the provider check deleted: nothing in the Opbox pack
    matched those names, so the availability filter alone was enough and the
    test proved nothing about dormancy. Naming them `opbox.*` removes that
    second guard, so only the PROVIDER can be what withholds the binding.

    It is also a real property in its own right: another adapter naming its
    verb `opbox.create_matter` must not inherit Opbox's canonical mapping.
    """
    store = await _register(_Door("hubspot", ("opbox.create_matter", "opbox.get_matter")))

    assert await store.list_capability_bindings(TENANT, "matter.open") == []
    assert await store.list_capability_bindings(TENANT, "matter.get") == []


@pytest.mark.asyncio
async def test_a_stale_pack_entry_maps_nothing_rather_than_inventing_a_binding():
    """A pack outlives the catalogue it maps.

    If Opbox retires an operation, the pack should bind the ones that remain
    and skip the one that is gone, rather than minting a binding onto an
    operation the provider does not expose.
    """
    store = await _register(_Door("opbox", ("opbox.get_matter",)))

    assert await store.list_capability_bindings(TENANT, "matter.open") == []
    assert len(await store.list_capability_bindings(TENANT, "matter.get")) == 1


@pytest.mark.asyncio
async def test_a_declared_claim_overrides_the_pack_for_the_same_operation():
    """Level 1 beats level 2, expressed as write order.

    The provider speaking about its own operation outranks a curator's guess,
    and they share a binding_id so the declaration replaces the guess instead
    of the two coexisting as rival routes.
    """

    from dataclasses import replace

    class _Declaring(_Door):
        def describe(self):
            specs = super().describe()
            return [replace(specs[0], implements="matter.create_custom"), *specs[1:]]

    store = await _register(_Declaring("opbox", ("opbox.create_matter",)))

    assert await store.list_capability_bindings(TENANT, "matter.open") == []
    declared = await store.list_capability_bindings(TENANT, "matter.create_custom")
    assert [b.created_from for b in declared] == ["declared"]
