"""The review queue, the derived catalogue, and the fences on both (A5).

``control.capability_binding.approve``/``.reject`` shipped with no inbox: an
operator could act on a binding only by already knowing its id. These are the
reads that make the gate usable, and the fences that keep them from turning a
review console into a disclosure of the tenant's wiring.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    RoutingPolicy,
    SourceOperation,
)
from boltrig.models.integrations import IntegrationConnection
from boltrig.store import InMemoryStore

T = "review-tenant"


async def _seeded() -> InMemoryStore:
    store = InMemoryStore()
    # A first-party door: no integration row behind it, so tenant-level.
    await store.upsert_provider_connection(
        ProviderConnection(
            id="pconn:opbox", tenant_id=T, label="Opbox", provider="opbox",
            adapter_id="opbox",
        )
    )
    # A member's PERSONAL connection. accounts[].id is an email address, which
    # is why visible_to exists at all.
    await store.upsert_integration_connection(
        IntegrationConnection(
            id="iconn:hubspot-personal", tenant_id=T, integration_id="hubspot",
            adapter_id="hubspot", label="Dana's HubSpot", health="ok",
            accounts=[{"id": "dana@example.test", "label": "Dana"}],
            level="user", scope_id="dana",
        )
    )
    await store.upsert_provider_connection(
        ProviderConnection(
            id="pconn:hubspot", tenant_id=T, label="Dana's HubSpot",
            provider="hubspot", adapter_id="hubspot",
            integration_connection_id="iconn:hubspot-personal",
        )
    )
    for operation_id, provider, connection, digest in (
        ("opbox.create_matter", "opbox", "pconn:opbox", "digest-open"),
        ("opbox.close_matter", "opbox", "pconn:opbox", "digest-close"),
        ("hubspot.contact.search", "hubspot", "pconn:hubspot", "digest-hs"),
    ):
        await store.upsert_source_operation(
            SourceOperation(
                id=operation_id, tenant_id=T, provider=provider,
                connection_id=connection, description=f"{operation_id} does a thing",
                schema_digest=digest,
            )
        )
    for binding_id, capability, operation, connection, status, digest in (
        ("cb:open", "matter.open", "opbox.create_matter", "pconn:opbox", "approved", "digest-open"),
        ("cb:close", "matter.close", "opbox.close_matter", "pconn:opbox", "proposed", "digest-close"),
        # Pinned to a digest the operation no longer carries: the drift case a
        # reviewer has to be able to see.
        ("cb:drifted", "matter.open", "opbox.close_matter", "pconn:opbox", "approved", "stale-digest"),
        ("cb:hubspot", "crm.contact.search", "hubspot.contact.search", "pconn:hubspot", "proposed", "digest-hs"),
    ):
        await store.upsert_capability_binding(
            CapabilityBinding(
                binding_id=binding_id, tenant_id=T, capability_id=capability,
                source_operation_id=operation, connection_id=connection,
                status=status, source_schema_digest=digest, created_from="mapping_pack",
            )
        )
    await store.upsert_routing_policy(
        RoutingPolicy(
            id="rp:open-read", tenant_id=T, capability_id="matter.open",
            binding_id="cb:open", operation_class="read",
        )
    )
    return store


def _headers(role: str = "admin", subject: str = "auditor") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": subject,
        "x-boltrig-role": role,
    }


@pytest.mark.security
async def test_the_review_queue_joins_the_operation_and_the_connection() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    body = client.get("/v1/capability-bindings?status=proposed", headers=_headers()).json()
    rows = {row["binding_id"]: row for row in body["bindings"]}

    # cb:hubspot is hidden by the OWNERSHIP fence: its provider connection
    # descends from Dana's personal integration row and the auditor is not Dana.
    assert set(rows) == {"cb:close"}
    assert body["needs_review"] == 1

    row = rows["cb:close"]
    assert row["capability"] == "matter.close@1"
    assert row["source_operation"]["description"] == "opbox.close_matter does a thing"
    assert row["connection"]["provider"] == "opbox"
    assert row["created_from"] == "mapping_pack"
    # The digests themselves are not in the response; the two questions a
    # reviewer asks are.
    assert row["schema_pinned"] is True and row["schema_current"] is True
    assert "digest-close" not in client.get(
        "/v1/capability-bindings", headers=_headers()
    ).text


@pytest.mark.security
async def test_schema_drift_is_visible_in_the_queue() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    rows = {
        row["binding_id"]: row
        for row in client.get("/v1/capability-bindings", headers=_headers()).json()["bindings"]
    }
    # The negative control sits beside it: cb:open pins the SAME operation shape
    # and reads current, so "schema_current: false" is a finding rather than a
    # field that is always false.
    assert rows["cb:drifted"]["schema_current"] is False
    assert rows["cb:open"]["schema_current"] is True


@pytest.mark.security
async def test_the_owner_of_a_personal_connection_sees_their_own_binding() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    dana = client.get(
        "/v1/capability-bindings", headers=_headers(subject="dana")
    ).json()
    assert "cb:hubspot" in {row["binding_id"] for row in dana["bindings"]}
    # And the fence is a fence, not a filter that hides everything: Dana still
    # sees the tenant-level Opbox bindings.
    assert "cb:open" in {row["binding_id"] for row in dana["bindings"]}


@pytest.mark.security
async def test_the_catalogue_is_derived_from_the_bindings_that_claim_it() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    body = client.get("/v1/capability-catalogue", headers=_headers()).json()
    catalogue = {row["capability_id"]: row for row in body["capabilities"]}

    assert set(catalogue) == {"matter.open", "matter.close"}
    assert catalogue["matter.open"]["implementations"] == 2
    assert catalogue["matter.open"]["approved"] == 2
    assert catalogue["matter.open"]["needs_review"] == 0
    assert catalogue["matter.open"]["routing_policies"] == 1
    assert catalogue["matter.open"]["providers"] == ["opbox"]
    assert catalogue["matter.close"]["needs_review"] == 1
    assert catalogue["matter.close"]["routing_policies"] == 0
    # crm.contact.search exists in the store and is absent here, because the
    # only binding claiming it is behind the ownership fence.
    assert "crm.contact.search" not in catalogue


@pytest.mark.security
async def test_routing_policies_are_scoped_to_visible_capabilities() -> None:
    store = await _seeded()
    # A policy for the fenced capability. Approve its binding first, because a
    # route to a proposed binding is refused at authoring time.
    await store.set_capability_binding_status(T, "cb:hubspot", "approved", "reviewer")
    await store.upsert_routing_policy(
        RoutingPolicy(
            id="rp:hidden", tenant_id=T, capability_id="crm.contact.search",
            binding_id="cb:hubspot", operation_class="read",
        )
    )
    client = TestClient(create_app(Kernel(store)))
    listed = client.get("/v1/routing-policies", headers=_headers()).json()
    assert [row["id"] for row in listed["routing_policies"]] == ["rp:open-read"]
    # Dana can see hers.
    dana = client.get("/v1/routing-policies", headers=_headers(subject="dana")).json()
    assert {row["id"] for row in dana["routing_policies"]} == {"rp:open-read", "rp:hidden"}


@pytest.mark.security
async def test_a_non_author_cannot_read_any_of_the_three() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    for path in (
        "/v1/capability-bindings",
        "/v1/capability-catalogue",
        "/v1/routing-policies",
    ):
        assert client.get(path, headers=_headers("member")).status_code == 403
        assert client.get(path, headers=_headers("admin")).status_code == 200


@pytest.mark.security
async def test_an_unknown_status_filter_returns_nothing_rather_than_everything() -> None:
    client = TestClient(create_app(Kernel(await _seeded())))
    body = client.get("/v1/capability-bindings?status=nonsense", headers=_headers()).json()
    # Fail-closed on a typo. Falling through to the unfiltered list would answer
    # "show me the rejected ones" with every binding the tenant has.
    assert body["bindings"] == [] and body["reason"] == "unknown_status"
