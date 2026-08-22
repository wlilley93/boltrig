"""Per-user integration credentials: precedence, the org gate, and the fences.

SEC-200     : precedence user -> org -> env/manifest, and
              allow_own_integration_credentials=False makes a member's own
              connection IGNORED rather than merely unreachable, so revoking the
              policy is enough on its own.
SEC-201     : a sealed credential resolves only for the scope it was sealed for,
              and a connection is visible only to the org or its own owner.
FR-INTCRED-01: setup and dispatch derive the SAME acting identity, so a personal
              credential is looked up under the id it was filed under.
FR-INTCRED-02: one active connection per adapter PER SCOPE - an org row and a
              user row coexist; two rows at one scope fail closed.
SEC-202     : an administrator can destroy a departed member's personal
              credential, and cannot read their provider identity doing it.
FR-INTCRED-03: the administrator verb serves exactly one case - it refuses the
              org's shared row and refuses the caller's own.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from boltrig.kernel.credentials import CredentialResolver
from boltrig.kernel.integration_credentials import (
    integration_manual_secret_ref,
    resolve_integration_credential,
)
from boltrig.kernel.integration_scope import acting_owner, pick_connection, scope_of
from boltrig.kernel.platform_routes.integrations import visible_to
from boltrig.models import CredentialResolution, InvocationContext, Organisation
from boltrig.models.integrations import IntegrationConnection
from boltrig.store.memory import InMemoryStore
from fastapi.testclient import TestClient

from boltrig.kernel.app import create_app

# The catalogue + adapter + contract fixture is 60 lines and already exists next
# door; duplicating it to reach the routes would be worse than importing it, and
# tests/approval is already imported across test modules the same way.
from boltrig.config.control_approval import control_approval_context
from boltrig.config.control_integrations import execute_integration_operation
from boltrig.config.control_safety import ControlConflict
from boltrig.kernel.hitl import canonical_approval_value
from tests.approval import approved_request
from tests.security.test_integration_connections import _headers, _kernel

T = "acme"
ADAPTER = "durable-tickets-adapter"
ROOT = Path(__file__).resolve().parents[2]


def _connection(level: str, scope_id: str, cred: str) -> IntegrationConnection:
    return IntegrationConnection(
        id=f"conn-{level}-{scope_id or 'org'}",
        tenant_id=T,
        integration_id="durable-tickets",
        adapter_id=ADAPTER,
        label=f"{level} tickets",
        credential_ref=cred,
        credential_owned=True,
        level=level,
        scope_id=scope_id,
    )


async def _seeded(*, allow_own: bool, rows: list[IntegrationConnection]) -> InMemoryStore:
    store = InMemoryStore()
    await store.create_org(
        Organisation(
            id=T, name="Acme", slug="acme", allow_own_integration_credentials=allow_own
        )
    )
    for row in rows:
        secret = {"opaque": f"{row.level}:{row.scope_id}"}
        credential = integration_manual_secret_ref(
            "durable-tickets", ADAPTER, "api_key", "tickets_v1", secret,
            level=row.level, scope_id=row.scope_id,
        )
        assert await store.create_integration_connection_with_credential(row, credential)
    return store


# --- SEC-200: precedence and the gate ---------------------------------------


@pytest.mark.invariant("SEC-200")
def test_own_credential_wins_only_when_the_org_allows_it():
    async def run(allow_own: bool) -> dict:
        store = await _seeded(
            allow_own=allow_own,
            rows=[_connection("org", T, "cred-org"), _connection("user", "alice", "cred-alice")],
        )
        resolved = await CredentialResolver(store).resolve_for_adapter(T, ADAPTER, "alice")
        assert resolved is not None
        return resolved.material

    # The whole point of the feature...
    assert asyncio.run(run(True)) == {"opaque": "user:alice"}
    # ...and the whole point of the gate: alice's row still EXISTS and is still
    # sealed, it is simply not consulted. Flipping the org back restores it with
    # no row surgery, which is what makes the policy a real off switch.
    assert asyncio.run(run(False)) == {"opaque": "org:acme"}


@pytest.mark.invariant("SEC-200")
def test_a_user_without_their_own_connection_gets_the_org_one():
    async def run() -> dict:
        store = await _seeded(allow_own=True, rows=[_connection("org", T, "cred-org")])
        resolved = await CredentialResolver(store).resolve_for_adapter(T, ADAPTER, "bob")
        assert resolved is not None
        return resolved.material

    assert asyncio.run(run()) == {"opaque": "org:acme"}


@pytest.mark.invariant("SEC-200")
def test_no_owner_reproduces_the_pre_scoping_behaviour_exactly():
    """Every caller that predates scoping passes no owner and must be unchanged."""

    async def run() -> dict:
        store = await _seeded(
            allow_own=True,
            rows=[_connection("org", T, "cred-org"), _connection("user", "alice", "cred-alice")],
        )
        resolved = await CredentialResolver(store).resolve_for_adapter(T, ADAPTER)
        assert resolved is not None
        return resolved.material

    assert asyncio.run(run()) == {"opaque": "org:acme"}


# --- SEC-201: the two fences ------------------------------------------------


@pytest.mark.invariant("SEC-201")
def test_a_sealed_credential_refuses_a_different_scope():
    sealed = integration_manual_secret_ref(
        "durable-tickets", ADAPTER, "api_key", "tickets_v1",
        {"opaque": "alices"}, level="user", scope_id="alice",
    )
    assert resolve_integration_credential(sealed, "c", ADAPTER, "user", "alice") is not None
    with pytest.raises(CredentialResolution):
        resolve_integration_credential(sealed, "c", ADAPTER, "user", "bob")
    with pytest.raises(CredentialResolution):
        resolve_integration_credential(sealed, "c", ADAPTER, "org", T)


@pytest.mark.invariant("SEC-201")
def test_a_credential_sealed_before_scoping_still_resolves_for_the_org():
    """The back-compat leg. Every production row predates level/scope_id, and a
    strict comparison would raise on all of them -- an outage, not a fence. A
    ref with no level is legacy, and legacy was necessarily org."""
    legacy = {
        "kind": "integration_manual_secret",
        "integration_id": "durable-tickets",
        "adapter_id": ADAPTER,
        "credential_kind": "api_key",
        "contract_version": "tickets_v1",
        "fields": {"opaque": "from-before"},
    }
    assert resolve_integration_credential(legacy, "c", ADAPTER, "org", T) is not None
    with pytest.raises(CredentialResolution):
        resolve_integration_credential(legacy, "c", ADAPTER, "user", "alice")


@pytest.mark.invariant("SEC-201")
def test_a_personal_connection_is_visible_only_to_its_owner():
    org = _connection("org", T, "cred-org")
    alice = _connection("user", "alice", "cred-alice")
    assert visible_to(org, "bob") and visible_to(org, "alice")
    assert visible_to(alice, "alice")
    assert not visible_to(alice, "bob")


# --- FR-INTCRED-01: the two identity derivations must agree -----------------


@pytest.mark.invariant("FR-INTCRED-01")
def test_setup_and_dispatch_derive_the_same_acting_identity():
    """A drift test, and the defect it guards is silent.

    If setup seals under `on_behalf_of or actor` and dispatch looks up by
    `on_behalf_of` alone, then for a person logged in directly -- where
    on_behalf_of is None -- the credential is filed under their user id and
    fetched under nothing. Resolution falls through to the org credential and
    the feature does nothing, with no error anywhere.
    """
    context = InvocationContext(tenant_id=T, actor="alice")
    assert context.on_behalf_of is None
    assert acting_owner(context) == "alice"

    delegated = InvocationContext(tenant_id=T, actor="agent-7", on_behalf_of="alice")
    assert acting_owner(delegated) == "alice"

    dispatch = (ROOT / "boltrig" / "kernel" / "dispatch.py").read_text(encoding="utf-8")
    assert "context.on_behalf_of or context.actor" in dispatch, (
        "dispatch must resolve credentials under the same identity acting_owner derives"
    )


# --- FR-INTCRED-02: uniqueness is per scope ---------------------------------


@pytest.mark.invariant("FR-INTCRED-02")
def test_an_org_and_a_user_connection_coexist_but_a_scope_cannot_duplicate():
    async def run() -> None:
        store = await _seeded(
            allow_own=True,
            rows=[_connection("org", T, "cred-org"), _connection("user", "alice", "cred-alice")],
        )
        applicable = await store.list_applicable_integration_connections_for_adapter(
            T, ADAPTER, "alice"
        )
        assert {row.level for row in applicable} == {"org", "user"}

        # A second row at the SAME scope is what the fence is for.
        duplicate = _connection("user", "alice", "cred-alice-2")
        duplicate.id = "conn-user-alice-again"
        assert not await store.create_integration_connection_with_credential(
            duplicate,
            integration_manual_secret_ref(
                "durable-tickets", ADAPTER, "api_key", "tickets_v1",
                {"opaque": "dupe"}, level="user", scope_id="alice",
            ),
        )

    asyncio.run(run())


@pytest.mark.invariant("FR-INTCRED-02")
def test_the_model_refuses_a_user_row_that_could_alias_or_borrow():
    """Two model invariants the layers above quietly rely on.

    The store's applicable-connections query passes `owner or ""` and so asks
    for scope_id='' when there is no owner; that is safe only because a user row
    can never HAVE an empty scope_id. And a user row pointing at a credential it
    does not own would let a member borrow the org's under their own
    attribution -- the audit would record the call as theirs.
    """
    with pytest.raises(ValueError):
        IntegrationConnection(
            id="c", tenant_id=T, integration_id="i", adapter_id=ADAPTER,
            label="l", credential_ref="r", credential_owned=True,
            level="user", scope_id="",
        )
    with pytest.raises(ValueError):
        IntegrationConnection(
            id="c", tenant_id=T, integration_id="i", adapter_id=ADAPTER,
            label="l", credential_ref="r", credential_owned=False,
            level="user", scope_id="alice",
        )
    # An org row still derives its scope rather than demanding one, so every
    # caller predating scoping keeps constructing a valid connection untouched.
    assert IntegrationConnection(
        id="c", tenant_id=T, integration_id="i", adapter_id=ADAPTER, label="l",
    ).scope_id == T


@pytest.mark.invariant("FR-INTCRED-02")
def test_the_env_manifest_binding_answers_for_the_org():
    """scope_of maps "no connection row" onto the org, because a manifest
    binding is org-wide by construction and has no other scope to be."""
    assert scope_of(None, T) == ("org", T)
    assert scope_of(_connection("user", "alice", "c"), T) == ("user", "alice")


@pytest.mark.invariant("FR-INTCRED-02")
def test_pick_connection_prefers_the_owner_row_by_level_not_by_order():
    async def run(rows: list[IntegrationConnection]) -> str:
        store = await _seeded(allow_own=True, rows=rows)
        picked = await pick_connection(store, T, ADAPTER, "alice")
        assert picked is not None
        return picked.level

    org = _connection("org", T, "cred-org")
    alice = _connection("user", "alice", "cred-alice")
    # Either insertion order, same answer: the store promises no ordering.
    assert asyncio.run(run([org, alice])) == "user"
    assert asyncio.run(run([alice, org])) == "user"


# --- the HTTP path, which is where the scope is decided --------------------


@pytest.mark.security
@pytest.mark.invariant("SEC-200")
def test_the_route_refuses_a_personal_connection_the_org_has_not_allowed():
    """Refused BEFORE anything is sealed, so no unreachable credential is left."""
    kernel, store = asyncio.run(_kernel(with_connection=False, manual_contract=True))
    client = TestClient(create_app(kernel))
    sentinel = "personal-token-MUST-NOT-PERSIST"
    response = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "fields": {
                "token": sentinel,
                "account_id": "alice",
                "account_label": "Alice",
            },
            "level": "user",
        },
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "own_integration_credentials_not_allowed"
    assert asyncio.run(store.list_integration_connections("integration-tenant")) == []
    assert sentinel not in repr(store._creds)
    assert sentinel not in repr(asyncio.run(store.audit_query("integration-tenant")))


@pytest.mark.security
@pytest.mark.invariant("SEC-201")
def test_an_org_and_a_personal_connection_coexist_and_only_the_owner_sees_theirs():
    tenant = "integration-tenant"
    kernel, store = asyncio.run(_kernel(with_connection=False, manual_contract=True))
    asyncio.run(
        store.create_org(
            Organisation(
                id=tenant,
                name="Integration",
                slug="integration",
                allow_own_integration_credentials=True,
            )
        )
    )
    client = TestClient(create_app(kernel))

    def connect(level: str, subject: str, token: str):
        return client.post(
            "/v1/integrations/tickets/secrets",
            json={
                "fields": {
                    "token": token,
                    "account_id": subject,
                    "account_label": subject.title(),
                },
                "level": level,
            },
            headers=_headers(subject=subject),
        )

    # The org's shared connection, then alice's own for the SAME adapter -- the
    # pair the old one-per-adapter unique index made impossible.
    assert connect("org", "admin", "org-token-000").status_code == 201
    assert connect("user", "alice", "alice-token-11").status_code == 201

    def listed(subject: str) -> dict[str, bool]:
        rows = client.get(
            "/v1/integrations/connections", headers=_headers(subject=subject)
        ).json()["connections"]
        return {row["level"]: row["is_own"] for row in rows}

    # Alice sees the org's and her own; Bob sees only the org's. accounts[].id is
    # routinely an email, so an unfenced list would hand Bob Alice's identity.
    assert listed("alice") == {"org": False, "user": True}
    assert listed("bob") == {"org": False}

    # And each resolves to the right credential.
    resolver_material = asyncio.run(
        kernel.credentials.resolve_for_adapter(tenant, "memory-tickets", "alice")
    ).material
    assert resolver_material["token"] == "alice-token-11"
    assert asyncio.run(
        kernel.credentials.resolve_for_adapter(tenant, "memory-tickets", "bob")
    ).material["token"] == "org-token-000"


# --- offboarding: an administrator reaching a departed member's credential ---


def _offboarding_kernel():
    """An org that allows personal credentials, with alice's own already sealed."""
    tenant = "integration-tenant"
    kernel, store = asyncio.run(_kernel(with_connection=False, manual_contract=True))
    asyncio.run(
        store.create_org(
            Organisation(
                id=tenant,
                name="Integration",
                slug="integration",
                allow_own_integration_credentials=True,
            )
        )
    )
    client = TestClient(create_app(kernel))

    def connect(level: str, subject: str, token: str):
        return client.post(
            "/v1/integrations/tickets/secrets",
            json={
                "fields": {
                    "token": token,
                    "account_id": f"{subject}@example.com",
                    "account_label": subject.title(),
                },
                "level": level,
            },
            headers=_headers(subject=subject),
        )

    assert connect("org", "admin", "org-token-000").status_code == 201
    assert connect("user", "alice", "alice-token-11").status_code == 201
    return kernel, store, client, tenant


@pytest.mark.security
@pytest.mark.invariant("SEC-202")
def test_an_administrator_sees_a_members_connection_without_their_provider_identity():
    _, _, client, _ = _offboarding_kernel()
    rows = client.get(
        "/v1/integrations/member-connections", headers=_headers(subject="admin")
    ).json()["connections"]
    assert [row["owner"] for row in rows] == ["alice"]
    # The whole point of the reduced projection: accounts[].id is alice's address
    # at the provider, and administering her row is not a reason to read it.
    assert "accounts" not in rows[0]
    assert "alice@example.com" not in repr(rows)


@pytest.mark.security
@pytest.mark.invariant("SEC-202")
def test_the_member_connection_list_is_author_only_and_excludes_your_own():
    _, _, client, _ = _offboarding_kernel()
    denied = client.get(
        "/v1/integrations/member-connections",
        headers=_headers(subject="bob", role="member"),
    )
    assert denied.status_code == 403
    # And an author sees only OTHER members' rows: alice administering asks about
    # everyone but herself, so the revoke below can refuse a self-revocation as a
    # fail-closed guard rather than as a dead end the console walks her into.
    own = client.get(
        "/v1/integrations/member-connections", headers=_headers(subject="alice")
    ).json()["connections"]
    assert own == []


@pytest.mark.security
@pytest.mark.invariant("SEC-202")
def test_revoking_a_members_connection_destroys_only_their_credential():
    kernel, store, client, tenant = _offboarding_kernel()
    rows = client.get(
        "/v1/integrations/member-connections", headers=_headers(subject="admin")
    ).json()["connections"]
    response = approved_request(
        client,
        kernel,
        tenant,
        "DELETE",
        f"/v1/integrations/member-connections/{rows[0]['id']}",
        headers=_headers(subject="admin"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "revoked"
    assert (body["level"], body["scope_id"]) == ("user", "alice")

    # Alice now falls back to the org credential, and the org's is untouched.
    for subject in ("alice", "bob"):
        assert asyncio.run(
            kernel.credentials.resolve_for_adapter(tenant, "memory-tickets", subject)
        ).material["token"] == "org-token-000"
    # And her sealed material is gone rather than merely unreachable.
    assert "alice-token-11" not in repr(store._creds)


@pytest.mark.security
@pytest.mark.invariant("FR-INTCRED-03")
def test_the_administrator_verb_refuses_the_org_row_and_your_own():
    kernel, store, client, tenant = _offboarding_kernel()
    rows = asyncio.run(store.list_integration_connections(tenant))
    by_level = {row.level: row.id for row in rows}

    # Both refusals are raised by the handler, which runs only on the approved
    # replay: revocation is high consequence, so the first call is always held.
    org = approved_request(
        client,
        kernel,
        tenant,
        "DELETE",
        f"/v1/integrations/member-connections/{by_level['org']}",
        headers=_headers(subject="admin"),
    )
    assert org.status_code == 409  # the wire reports the CLASS, not the message

    # Alice may disconnect her own -- through control.integration.revoke, not
    # this verb. One verb per case is what keeps the audit able to say which of
    # the two things happened.
    own = approved_request(
        client,
        kernel,
        tenant,
        "DELETE",
        f"/v1/integrations/member-connections/{by_level['user']}",
        headers=_headers(subject="alice"),
    )
    assert own.status_code == 409
    # Neither refusal touched anything: both credentials still resolve.
    assert asyncio.run(
        kernel.credentials.resolve_for_adapter(tenant, "memory-tickets", "alice")
    ).material["token"] == "alice-token-11"
    assert asyncio.run(
        kernel.credentials.resolve_for_adapter(tenant, "memory-tickets", "bob")
    ).material["token"] == "org-token-000"

    # And the two refusals ARE distinct, which only the verb can show: the
    # transport collapses every ControlConflict onto one reason string.
    for level, subject, expected in (
        ("org", "admin", "not_a_member_integration_connection"),
        ("user", "alice", "use_integration_revoke_for_your_own_connection"),
    ):
        with pytest.raises(ControlConflict) as raised:
            asyncio.run(
                _revoke_member_directly(kernel, store, tenant, by_level[level], subject)
            )
        assert str(raised.value) == expected


async def _revoke_member_directly(kernel, store, tenant, connection_id, subject):
    """Call the verb past the HTTP layer, carrying the approval evidence the
    handler demands, so a ControlConflict surfaces with its own message."""
    params = {"connection_id": connection_id}
    context = InvocationContext(tenant_id=tenant, actor=subject)
    # The role the HTTP door stamps on; the pre-authorisation reads it from here.
    context.extra["principal_role"] = "org-admin"
    resolved = await control_approval_context(
        store, kernel.loader, "control.integration.revoke_member", params, context
    )
    context.extra["approval_request_fingerprint"] = "f" * 64
    context.extra["approval_resource_context"] = canonical_approval_value(resolved)
    return await execute_integration_operation(
        store,
        kernel.loader,
        kernel.credentials,
        "control.integration.revoke_member",
        params,
        context,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-203")
def test_a_member_can_disconnect_the_credential_a_member_may_connect():
    """Connecting is low consequence and revoking is high, and every
    high-consequence control.integration.* verb was gated on an author role -- so
    a member could seal a personal token and never destroy it."""
    tenant = "integration-tenant"
    kernel, store = asyncio.run(_kernel(with_connection=False, manual_contract=True))
    asyncio.run(
        store.create_org(
            Organisation(
                id=tenant,
                name="Integration",
                slug="integration",
                allow_own_integration_credentials=True,
            )
        )
    )
    client = TestClient(create_app(kernel))
    member = _headers(subject="carol", role="member")

    created = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "fields": {
                "token": "carol-token-999",
                "account_id": "carol@example.com",
                "account_label": "Carol",
            },
            "level": "user",
        },
        headers=member,
    )
    assert created.status_code == 201
    connection_id = created.json()["connection"]["id"]

    revoked = approved_request(
        client, kernel, tenant, "DELETE",
        f"/v1/integrations/connections/{connection_id}", headers=member,
    )
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert "carol-token-999" not in repr(store._creds)

    # The relaxation is exactly this one case: the org's shared row is still
    # administration, and a member is still refused it.
    org = client.post(
        "/v1/integrations/tickets/secrets",
        json={
            "fields": {
                "token": "org-token-0000",
                "account_id": "ops@example.com",
                "account_label": "Ops",
            },
            "level": "org",
        },
        headers=_headers(subject="admin"),
    )
    assert org.status_code == 201
    denied = client.delete(
        f"/v1/integrations/connections/{org.json()['connection']['id']}",
        headers=member,
    )
    assert denied.status_code == 403
