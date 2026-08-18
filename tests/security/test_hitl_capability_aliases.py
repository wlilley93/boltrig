"""A held routed call must reach the people who administer what it touches.

A capability-addressed call is recorded under the name the CALLER typed, so the
approver check ran against `crm.contact.create` while the person who administers
HubSpot holds `hubspot.contact.create`. They could neither see the request nor
answer it, and the call sat waiting for a human who did not exist.

Authority over the ACTION is the question, not authority over the spelling that
reached it - the same principle that made the always-ask list resolve through
stored bindings rather than string membership.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    HITLStatus,
    HITLType,
    TenantPermissions,
)
from boltrig.models.capability_routing import (
    CapabilityBinding,
    ProviderConnection,
    SourceOperation,
)
from boltrig.store import InMemoryStore

TENANT = "acme"


async def _kernel_with_binding(status: str = "approved") -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(
        TenantPermissions(TENANT, GrantSet.of(["crm.*", "hubspot.*"]))
    )
    await store.upsert_provider_connection(
        ProviderConnection(
            id="pconn:hubspot",
            tenant_id=TENANT,
            label="HubSpot - UK Sales",
            provider="hubspot",
        )
    )
    await store.upsert_source_operation(
        SourceOperation(
            id="hubspot.contact.create", tenant_id=TENANT, provider="hubspot"
        )
    )
    await store.upsert_capability_binding(
        CapabilityBinding(
            binding_id="cb:hubspot:create",
            tenant_id=TENANT,
            capability_id="crm.contact.create",
            source_operation_id="hubspot.contact.create",
            connection_id="pconn:hubspot",
            status=status,
        )
    )
    return Kernel(store)


def _held(kernel: Kernel, verb: str):
    return asyncio.run(
        kernel.hitl.create(
            tenant_id=TENANT,
            run_id="r",
            type=HITLType.APPROVAL,
            question=f"Approve {verb} ?",
            verb=verb,
            requested_by="requesting-agent",
            request_fingerprint=f"fp-{verb}",
        )
    )


def _respond(client: TestClient, request_id: str, grants: str):
    return client.post(
        f"/v1/hitl/{request_id}/respond",
        json={"decision": "approve"},
        headers={
            "x-boltrig-tenant": TENANT,
            "x-boltrig-subject": "integration-admin",
            "x-boltrig-tier": "human",
            "x-boltrig-role": "agent",
            "x-boltrig-grants": grants,
        },
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_the_source_operations_administrator_can_answer_a_held_capability_call():
    """The live hole: the approver who can perform the action themselves."""
    kernel = asyncio.run(_kernel_with_binding())
    client = TestClient(create_app(kernel, platform={}))
    request = _held(kernel, "crm.contact.create")

    assert _respond(client, request.id, "hubspot.contact.create").status_code == 200
    assert asyncio.run(kernel.hitl.get(TENANT, request.id)).status is HITLStatus.ANSWERED


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_the_capability_holder_can_answer_a_held_source_operation_call():
    """The mirror, so the rule is symmetric rather than a patch in one direction."""
    kernel = asyncio.run(_kernel_with_binding())
    client = TestClient(create_app(kernel, platform={}))
    request = _held(kernel, "hubspot.contact.create")

    assert _respond(client, request.id, "crm.contact.create").status_code == 200


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_an_unrelated_grant_still_cannot_answer():
    """The widening is bounded by the BINDING, not by sharing a namespace."""
    kernel = asyncio.run(_kernel_with_binding())
    client = TestClient(create_app(kernel, platform={}))
    request = _held(kernel, "crm.contact.create")

    assert _respond(client, request.id, "hubspot.contact.read").status_code == 403
    assert asyncio.run(kernel.hitl.get(TENANT, request.id)).status is HITLStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_an_unapproved_binding_confers_no_authority():
    """A proposed mapping serves no route, so it must confer no approval reach -
    the same set routing uses, for the same reason."""
    kernel = asyncio.run(_kernel_with_binding(status="proposed"))
    client = TestClient(create_app(kernel, platform={}))
    request = _held(kernel, "crm.contact.create")

    assert _respond(client, request.id, "hubspot.contact.create").status_code == 403
