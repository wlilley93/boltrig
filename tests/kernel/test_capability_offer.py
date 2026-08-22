"""What the model is offered once a capability is approved (SPEC §10 step 1).

Approving a binding already made ``matter.open`` dispatchable. This is the last
mile: until the OFFER carries the canonical name, only a caller who already
knew it could reach it, and the model never would.
"""

from __future__ import annotations

import pytest

from boltrig.kernel.capability_offer import offer_candidates
from boltrig.models import GrantSet
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    SourceOperation,
)
from boltrig.models.registry import Consequence, Noun, Verb
from boltrig.store import InMemoryStore

T = "offer"


async def _store(*, status: str = "approved", consequence_hint: str = "low") -> InMemoryStore:
    store = InMemoryStore()
    await store.upsert_noun(Noun(id="matter", tenant_id=T))
    await store.upsert_verb(
        Verb(
            id="opbox.create_matter",
            tenant_id=T,
            noun_id="matter",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            output_schema={"type": "object"},
            description="Create a matter",
        )
    )
    await store.upsert_verb(
        Verb(
            id="opbox.unmapped_thing",
            tenant_id=T,
            noun_id="matter",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            description="Something with no canonical face",
        )
    )
    await store.upsert_provider_connection(
        ProviderConnection(
            id="pconn:opbox", tenant_id=T, label="Opbox", provider="opbox", adapter_id="opbox"
        )
    )
    await store.upsert_source_operation(
        SourceOperation(
            id="opbox.create_matter",
            tenant_id=T,
            provider="opbox",
            connection_id="pconn:opbox",
            description="Create a matter",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            output_schema={"type": "object"},
            consequence_hint=consequence_hint,
        )
    )
    await store.upsert_capability_binding(
        CapabilityBinding(
            binding_id="cb:pconn:opbox:opbox.create_matter",
            tenant_id=T,
            capability_id="matter.open",
            source_operation_id="opbox.create_matter",
            connection_id="pconn:opbox",
            status=status,
        )
    )
    return store


def _permits(*patterns: str):
    grants = GrantSet.of(list(patterns))
    return grants.permits


async def _ids(store, *patterns: str) -> set[str]:
    return {v.id for v in await offer_candidates(store, T, permits=_permits(*patterns))}


@pytest.mark.asyncio
async def test_the_model_is_offered_the_canonical_name_not_the_provider_one():
    store = await _store()

    offered = await _ids(store, "matter.*", "opbox.*")

    assert "matter.open" in offered
    # THE POINT OF THE DOCTRINE: the provider's name is gone from the offer.
    assert "opbox.create_matter" not in offered


@pytest.mark.asyncio
async def test_an_operation_with_no_canonical_face_is_still_offered():
    store = await _store()

    assert "opbox.unmapped_thing" in await _ids(store, "matter.*", "opbox.*")


@pytest.mark.asyncio
async def test_a_proposed_binding_changes_the_offer_not_at_all():
    store = await _store(status="proposed")

    offered = await _ids(store, "matter.*", "opbox.*")

    assert "matter.open" not in offered
    assert "opbox.create_matter" in offered


@pytest.mark.asyncio
async def test_the_capability_needs_both_grants_the_dispatcher_will_demand():
    """routing.grant_verbs requires the capability AND the source operation.

    Offering on the capability grant alone would put a tool in front of a model
    that the chokepoint then refuses, which is worse than not offering it.
    """
    store = await _store()

    offered = await _ids(store, "matter.*")  # no opbox.* grant

    assert "matter.open" not in offered


@pytest.mark.asyncio
async def test_a_caller_without_the_capability_grant_keeps_the_raw_verb():
    """THE REGRESSION THIS AVOIDS, and §11.10 names it.

    Grants are verb-id shaped. Suppressing the source operation unconditionally
    would leave a caller granted opbox.* with neither the raw verb nor the
    canonical one, so the tool would vanish rather than be renamed. Suppression
    happens only where the capability actually took its place.
    """
    store = await _store()

    offered = await _ids(store, "opbox.*")  # no matter.* grant

    assert "opbox.create_matter" in offered
    assert "matter.open" not in offered


@pytest.mark.asyncio
async def test_a_binding_may_raise_its_operations_consequence_never_lower_it():
    store = await _store(consequence_hint="high")

    offered = await offer_candidates(store, T, permits=_permits("matter.*", "opbox.*"))
    capability = next(v for v in offered if v.id == "matter.open")

    assert capability.consequence is Consequence.HIGH


@pytest.mark.asyncio
async def test_the_capability_carries_the_contract_of_the_binding_behind_it():
    """Until transforms land, a capability's contract IS its binding's (§11.9).

    Stated as a test so the day the canonical schema replaces the provider's,
    this is what has to change.
    """
    store = await _store()

    offered = await offer_candidates(store, T, permits=_permits("matter.*", "opbox.*"))
    capability = next(v for v in offered if v.id == "matter.open")

    assert capability.input_schema["properties"] == {"name": {"type": "string"}}
    assert capability.noun_id == "matter"


@pytest.mark.asyncio
async def test_a_tenant_with_no_bindings_is_offered_exactly_what_it_was_before():
    store = InMemoryStore()
    await store.upsert_noun(Noun(id="matter", tenant_id=T))
    await store.upsert_verb(
        Verb(
            id="opbox.create_matter",
            tenant_id=T,
            noun_id="matter",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
    )

    assert await _ids(store, "opbox.*") == {"opbox.create_matter"}
