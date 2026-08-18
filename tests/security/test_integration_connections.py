"""Decision-0021 integration catalogue and connection honesty contracts."""

import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    CredentialResolution,
    GrantSet,
    InvocationContext,
    TenantPermissions,
)
from boltrig.models.integrations import (
    IntegrationCatalogueRecord,
    IntegrationConnection,
)
from boltrig.models.integration_auth import (
    IntegrationSecretContract,
    IntegrationSecretField,
)
from boltrig.store import InMemoryStore
from tests.approval import approved_request

T = "integration-tenant"


def _headers(
    tenant: str = T,
    subject: str = "alice",
    role: str = "org-admin",
    grants: str = "*",
) -> dict[str, str]:
    return {
        "x-boltrig-tenant": tenant,
        "x-boltrig-subject": subject,
        "x-boltrig-role": role,
        "x-boltrig-grants": grants,
    }


def _manual_contract() -> IntegrationSecretContract:
    return IntegrationSecretContract(
        version="tickets_v1",
        credential_kind="api_key",
        fields=(
            IntegrationSecretField(
                name="token",
                label="API token",
                input_kind="token",
                min_length=12,
                max_length=200,
            ),
            IntegrationSecretField(
                name="account_id",
                label="Account ID",
                input_kind="text",
                secret=False,
                max_length=100,
            ),
            IntegrationSecretField(
                name="account_label",
                label="Account label",
                input_kind="text",
                secret=False,
                max_length=100,
            ),
        ),
        account_id_field="account_id",
        account_label_field="account_label",
    )


async def _kernel(
    *, with_connection: bool = True, manual_contract: bool = False
) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    store.set_tenant_permissions(TenantPermissions("rival", GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
    await kernel.loader.refresh_health()
    await store.upsert_integration_catalogue(
        IntegrationCatalogueRecord(
            id="tickets",
            tenant_id=T,
            label="Reviewed tickets",
            category="work",
            transport="rest",
            auth=["oauth2", "manual_secret"],
            description="The reviewed ticket adapter.",
            certification="certified",
            adapter_id="memory-tickets",
            secret_contract=_manual_contract() if manual_contract else None,
        )
    )
    await store.upsert_integration_catalogue(
        IntegrationCatalogueRecord(
            id="tickets",
            tenant_id="rival",
            label="Rival private catalogue",
            category="work",
            transport="rest",
            auth=[],
            description="Must remain tenant isolated.",
        )
    )
    if with_connection:
        await store.set_credential_ref(
            T,
            "integration:tickets:credential",
            {"store": "env", "ref": "TICKETS_TOKEN"},
        )
        kernel.credentials.bind_adapter_credential(
            T, "memory-tickets", "integration:tickets:credential"
        )
        await store.upsert_integration_connection(
            IntegrationConnection(
                id="conn-tickets",
                tenant_id=T,
                integration_id="tickets",
                adapter_id="memory-tickets",
                label="Operations tickets",
                health="pending",
                credential_ref="integration:tickets:credential",
                credential_owned=True,
                accounts=[
                    {
                        "id": "ops",
                        "label": "Operations",
                        "selected": True,
                        "secret": "MUST-NOT-PROJECT",
                    }
                ],
            )
        )
    return kernel, store


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_catalogue_and_connections_derive_only_safe_reviewed_registry_state():
    kernel, _ = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    catalogue = client.get("/v1/integrations/catalogue", headers=_headers()).json()["integrations"]
    assert catalogue == [
        {
            "id": "tickets",
            "label": "Reviewed tickets",
            "category": "work",
            "transport": "rest",
            "auth": ["oauth2", "manual_secret"],
            "description": "The reviewed ticket adapter.",
            "certification": "certified",
            "setup_copy": None,
            "access_copy": None,
            "available": True,
            "availability_reason": None,
            "setup_supported": False,
            "setup_contract": None,
            "enabled_tools": ["ticket.create", "ticket.read"],
        }
    ]
    assert "Rival private catalogue" not in repr(catalogue)
    assert "module_ref" not in repr(catalogue)

    response = client.get("/v1/integrations/connections", headers=_headers()).json()["connections"]
    assert response[0]["credential_ref_present"] is True
    assert response[0]["accounts"] == [{"id": "ops", "label": "Operations", "selected": True}]
    assert response[0]["enabled_tools"] == ["ticket.create", "ticket.read"]
    assert "MUST-NOT-PROJECT" not in repr(response)
    assert (
        client.get("/v1/integrations/catalogue", headers=_headers(tenant="rival")).json()[
            "integrations"
        ][0]["label"]
        == "Rival private catalogue"
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_unsupported_setup_rejects_secrets_and_oauth_without_creating_state():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    before = asyncio.run(store.list_integration_connections(T))
    oauth = client.post("/v1/integrations/tickets/oauth/start", headers=_headers())
    assert oauth.status_code == 409
    assert oauth.json()["reason"] == "oauth_provider_not_configured"
    sentinel = "arbitrary-secret-MUST-NOT-PERSIST"
    secret = client.post(
        "/v1/integrations/tickets/secrets",
        json={"fields": {"token": sentinel}},
        headers=_headers(),
    )
    assert secret.status_code == 409
    assert secret.json()["reason"] == "typed_secret_contract_not_configured"
    assert asyncio.run(store.list_integration_connections(T)) == before
    assert sentinel not in repr(store._creds)
    assert sentinel not in repr(asyncio.run(store.audit_query(T)))


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
@pytest.mark.invariant("SEC-140")
def test_certified_manual_contract_seals_once_and_projects_only_account_metadata():
    kernel, store = asyncio.run(_kernel(with_connection=False, manual_contract=True))
    client = TestClient(create_app(kernel))
    catalogue = client.get("/v1/integrations/catalogue", headers=_headers()).json()["integrations"][
        0
    ]
    assert catalogue["setup_supported"] is True
    assert catalogue["setup_contract"] == {
        "kind": "manual_secret",
        "version": "tickets_v1",
        "fields": [
            {
                "name": "token",
                "label": "API token",
                "input_kind": "token",
                "secret": True,
                "required": True,
                "min_length": 12,
                "max_length": 200,
            },
            {
                "name": "account_id",
                "label": "Account ID",
                "input_kind": "text",
                "secret": False,
                "required": True,
                "min_length": 1,
                "max_length": 100,
            },
            {
                "name": "account_label",
                "label": "Account label",
                "input_kind": "text",
                "secret": False,
                "required": True,
                "min_length": 1,
                "max_length": 100,
            },
        ],
    }
    sentinel = "ticket-token-MUST-NOT-ECHO"
    response = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "label": "Support desk",
            "fields": {
                "token": sentinel,
                "account_id": "support",
                "account_label": "Support",
            },
        },
        headers=_headers(),
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "connected"
    assert payload["connection"]["credential_ref_present"] is True
    assert payload["connection"]["accounts"] == [
        {"id": "support", "label": "Support", "selected": True}
    ]
    assert sentinel not in response.text
    assert sentinel not in repr(store._creds)
    assert sentinel not in repr(asyncio.run(store.audit_query(T)))
    assert any(
        event.verb == "control.integration.connect"
        and event.status == "ok"
        and event.detail["params"]
        == {
            # level joins the keys-only audit projection: it is routing,
            # not secret, and only NAMES are recorded here anyway. scope_id
            # is deliberately absent -- it never crosses the wire, because the
            # kernel derives the owner from the authenticated caller.
            "keys": ["integration_id", "label", "level", "secret"],
            "count": 4,
        }
        for event in asyncio.run(store.audit_query(T))
    )
    connection = asyncio.run(store.list_integration_connections(T))[0]
    credential = asyncio.run(kernel.credentials.resolve_for_adapter(T, "memory-tickets"))
    assert credential is not None
    assert credential.id == connection.credential_ref
    assert credential.material == {
        "token": sentinel,
        "account_id": "support",
        "account_label": "Support",
    }

    duplicate = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "fields": {
                "token": "replacement-MUST-NOT-PERSIST",
                "account_id": "replacement",
                "account_label": "Replacement",
            }
        },
        headers=_headers(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["reason"] == "adapter_credential_already_bound"
    assert len(asyncio.run(store.list_integration_connections(T))) == 1


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_manual_contract_rejects_unknown_missing_and_non_author_fields_without_state():
    kernel, store = asyncio.run(_kernel(with_connection=False, manual_contract=True))
    client = TestClient(create_app(kernel))
    sentinel = "unknown-MUST-NOT-PERSIST"
    unknown = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "fields": {
                "token": "valid-ticket-token",
                "account_id": "support",
                "account_label": "Support",
                sentinel: sentinel,
            }
        },
        headers=_headers(),
    )
    assert unknown.status_code == 400
    assert unknown.json()["reason"] == "unknown_fields"
    assert sentinel not in unknown.text
    missing = client.post(
        "/v1/integrations/tickets/secrets",
        json={"fields": {"token": "valid-ticket-token"}},
        headers=_headers(),
    )
    assert missing.status_code == 400
    assert missing.json()["reason"] == "required_field_missing"
    denied = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "fields": {
                "token": "valid-ticket-token",
                "account_id": "support",
                "account_label": "Support",
            }
        },
        headers=_headers(role="member"),
    )
    assert denied.status_code == 403
    assert asyncio.run(store.list_integration_connections(T)) == []
    assert repr(store._creds) == "{}"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
@pytest.mark.invariant("SEC-140")
async def test_direct_control_setup_keeps_every_provider_field_out_of_projections():
    kernel, store = await _kernel(with_connection=False, manual_contract=True)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store,
            loader=kernel.loader,
            registry=kernel.registry,
            credentials=kernel.credentials,
        ),
    )
    sentinel = "opaque-value-MUST-NOT-PROJECT"
    output = await kernel.invoke(
        "control",
        "control.integration.connect",
        {
            "integration_id": "tickets",
            "label": "Support",
            "secret": {
                "token": sentinel,
                "account_id": "support",
                "account_label": "Support",
            },
        },
        InvocationContext(
            tenant_id=T,
            actor="alice",
            actor_tier="human",
            grants=GrantSet.of(["*"]),
            run_id="integration-connect-run",
            extra={"principal_role": "org-admin"},
        ),
    )

    assert output["integration_id"] == "tickets"
    events = kernel.events.snapshot(T, "integration-connect-run")
    call = next(event for event in events if event["type"] == "tool_call")
    assert call["input"] == {
        "integration_id": "tickets",
        "label": "Support",
        "secret": "[redacted]",
    }
    projected = json.dumps(events) + repr(await store.audit_query(T))
    assert sentinel not in projected
    # Dynamic setup is durable authority, not a process-local resolver map:
    # both fresh kernels represent restart/another replica over the same store.
    for fresh_kernel in (Kernel(store), Kernel(store)):
        credential = await fresh_kernel.credentials.resolve_for_adapter(T, "memory-tickets")
        assert credential is not None and credential.material["token"] == sentinel

    connection = await store.get_integration_connection(T, output["connection_id"])
    assert connection is not None and connection.credential_ref
    await store.delete_credential_ref(T, connection.credential_ref)
    with pytest.raises(CredentialResolution, match="no credential reference"):
        await Kernel(store).credentials.resolve_for_adapter(T, "memory-tickets")


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
async def test_atomic_setup_failure_leaves_neither_connection_nor_credential(
    monkeypatch,
):
    import boltrig.store.integration_atomic as integration_store
    from boltrig.kernel.integration_credentials import integration_manual_secret_ref

    store = InMemoryStore()
    connection = IntegrationConnection(
        id="conn-failure",
        tenant_id=T,
        integration_id="tickets",
        adapter_id="memory-tickets",
        label="Failure",
        credential_ref="cred-failure",
        credential_owned=True,
    )
    credential = integration_manual_secret_ref(
        "tickets",
        "memory-tickets",
        "api_key",
        "tickets_v1",
        {"opaque": "MUST-NOT-PERSIST"},
        level="org",
        scope_id="acme",
    )

    def fail_seal(_credential):
        raise RuntimeError("injected seal failure")

    monkeypatch.setattr(integration_store, "seal_ref", fail_seal)
    with pytest.raises(RuntimeError, match="injected seal failure"):
        await store.create_integration_connection_with_credential(connection, credential)
    assert await store.get_integration_connection(T, connection.id) is None
    assert not await store.has_credential_ref(T, connection.credential_ref)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
async def test_ambiguous_active_connection_state_fails_closed():
    store = InMemoryStore()
    first = IntegrationConnection(
        id="conn-ambiguous-a",
        tenant_id=T,
        integration_id="tickets",
        adapter_id="memory-tickets",
        label="First",
        credential_ref="cred-ambiguous-a",
    )
    second = IntegrationConnection(
        id="conn-ambiguous-b",
        tenant_id=T,
        integration_id="tickets",
        adapter_id="memory-tickets",
        label="Second",
        credential_ref="cred-ambiguous-b",
    )
    # upsert is an internal projection/update seam, so model corrupt legacy
    # state through it. Normal atomic create and PostgreSQL's partial unique
    # index both prevent this shape.
    await store.upsert_integration_connection(first)
    await store.upsert_integration_connection(second)
    await store.set_credential_ref(T, first.credential_ref, {"secret": "first"})
    await store.set_credential_ref(T, second.credential_ref, {"secret": "second"})

    with pytest.raises(CredentialResolution, match="multiple active integration connections"):
        await Kernel(store).credentials.resolve_for_adapter(T, "memory-tickets")


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
async def test_process_and_durable_credential_disagreement_fails_closed():
    store = InMemoryStore()
    connection = IntegrationConnection(
        id="conn-durable-conflict",
        tenant_id=T,
        integration_id="tickets",
        adapter_id="memory-tickets",
        label="Durable",
        credential_ref="cred-durable",
    )
    await store.upsert_integration_connection(connection)
    await store.set_credential_ref(
        T,
        connection.credential_ref,
        {"store": "env", "ref": "DURABLE_TOKEN"},
    )
    kernel = Kernel(store)
    kernel.credentials.bind_adapter_credential(T, "memory-tickets", "cred-process-local")

    with pytest.raises(CredentialResolution, match="conflicting credential references"):
        await kernel.credentials.resolve_for_adapter(T, "memory-tickets")


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_health_is_registry_derived_and_revoke_drops_only_the_owned_reference():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    health = client.get("/v1/integrations/connections/conn-tickets/health", headers=_headers())
    assert health.status_code == 200
    assert health.json()["connection"]["health"] == "ok"
    assert health.json()["connection"]["last_checked_at"]
    assert (
        client.delete(
            "/v1/integrations/connections/conn-tickets",
            headers=_headers(role="member"),
        ).status_code
        == 403
    )
    revoked = approved_request(
        client,
        kernel,
        T,
        "DELETE",
        "/v1/integrations/connections/conn-tickets",
        headers=_headers(),
    )
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    row = asyncio.run(store.get_integration_connection(T, "conn-tickets"))
    assert row is not None and row.health == "revoked"
    assert row.credential_ref is None and row.revoked_at is not None
    assert asyncio.run(store.get_credential_ref(T, "integration:tickets:credential")) is None
    assert asyncio.run(kernel.credentials.resolve_for_adapter(T, "memory-tickets")) is None
    public = client.get("/v1/integrations/connections", headers=_headers()).json()["connections"][0]
    assert public["credential_ref_present"] is False
    assert public["enabled_tools"] == []
    assert (
        approved_request(
            client,
            kernel,
            T,
            "DELETE",
            "/v1/integrations/connections/conn-tickets",
            headers=_headers(),
        ).json()["status"]
        == "revoked"
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_health_probe_cannot_resurrect_a_connection_revoked_while_refreshing(
    monkeypatch,
):
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    refresh_started = threading.Event()
    allow_refresh = threading.Event()
    original_refresh = kernel.loader.refresh_health

    async def delayed_refresh():
        refresh_started.set()
        assert await asyncio.to_thread(allow_refresh.wait, 5)
        await original_refresh()

    monkeypatch.setattr(kernel.loader, "refresh_health", delayed_refresh)
    result: dict[str, object] = {}

    def request_health() -> None:
        result["response"] = client.get(
            "/v1/integrations/connections/conn-tickets/health",
            headers=_headers(),
        )

    request_thread = threading.Thread(target=request_health)
    request_thread.start()
    assert refresh_started.wait(5)
    revoked, credential_ref, deleted = asyncio.run(
        store.revoke_integration_connection_with_credential(T, "conn-tickets")
    )
    assert revoked is not None and revoked.health == "revoked"
    assert credential_ref == "integration:tickets:credential"
    assert deleted is True
    allow_refresh.set()
    request_thread.join(5)
    assert not request_thread.is_alive()

    response = result["response"]
    assert response.status_code == 200
    assert response.json()["connection"]["health"] == "revoked"
    assert response.json()["connection"]["credential_ref_present"] is False
    stored = asyncio.run(store.get_integration_connection(T, "conn-tickets"))
    assert stored is not None and stored.health == "revoked"
    assert stored.credential_ref is None
    assert asyncio.run(
        store.get_credential_ref(T, "integration:tickets:credential")
    ) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_a_connection_is_listed_only_to_someone_who_can_use_it():
    """The list answers "what can I use", not "what has this tenant wired up".

    Hardening `route_required` so an ungranted caller could not enumerate the
    tenant's connected systems left this door open one module over: the same
    labels, accounts and tool lists were readable by any authenticated member,
    with no grant or role check at all (SPEC 11.11). An author still sees
    everything, because administering connections is the job.
    """
    kernel, _ = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))

    author = client.get("/v1/integrations/connections", headers=_headers()).json()
    assert [row["label"] for row in author["connections"]] == ["Operations tickets"]

    granted = client.get(
        "/v1/integrations/connections",
        headers=_headers(role="member", grants="ticket.read"),
    ).json()
    assert [row["label"] for row in granted["connections"]] == ["Operations tickets"]

    stranger = client.get(
        "/v1/integrations/connections",
        headers=_headers(role="member", grants="unrelated.verb"),
    ).json()
    assert stranger["connections"] == []
    # ... and the refusal is a true empty answer, not an error the console has
    # to special-case.
    assert "Operations tickets" not in repr(stranger)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-06")
def test_the_catalogue_stays_a_shelf_but_stops_naming_tools_you_cannot_call():
    """Knowing an integration is SUPPORTED discloses nothing about this tenant,
    so the shelf stays visible to a member. Which tools it has bound does, so
    that field narrows to what the caller may actually call."""
    kernel, _ = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))

    author = client.get("/v1/integrations/catalogue", headers=_headers()).json()
    assert author["integrations"][0]["enabled_tools"] == ["ticket.create", "ticket.read"]

    member = client.get(
        "/v1/integrations/catalogue",
        headers=_headers(role="member", grants="ticket.read"),
    ).json()
    # The shelf entry is still there - "Reviewed tickets" is the CATALOGUE label,
    # not the connection's - and only its tool list narrowed.
    assert [row["label"] for row in member["integrations"]] == ["Reviewed tickets"]
    assert member["integrations"][0]["enabled_tools"] == ["ticket.read"]
