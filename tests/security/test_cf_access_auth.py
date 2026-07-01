"""Cloudflare Access auth: the kernel derives the principal from a verified
Access assertion, never from the request (SEC-01/02, IAM-09).

Cloudflare Access logs the user in at the edge and injects a signed JWT
(Cf-Access-Jwt-Assertion) on every request to the protected hostname. The kernel
verifies that JWT and maps the authenticated email to a role. These tests use a
stub verifier (the RS256/JWKS round-trip is covered by test_auth.py's OidcVerifier
test) and prove the mapping + fail-closed behaviour end-to-end through create_app.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.identity.auth import build_cf_access_resolver
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
HDR = "cf-access-jwt-assertion"


class _StubVerifier:
    """Accepts 'good.<email>' and returns that email as the claim; rejects else."""

    async def verify(self, token: str) -> dict:
        if not token.startswith("good."):
            raise ValueError("bad assertion")
        return {"email": token.split(".", 1)[1], "sub": "u-123"}


async def _kernel() -> Kernel:
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _client(role_map=None, default_role="none") -> TestClient:
    resolver = build_cf_access_resolver(
        verifier=_StubVerifier(),
        tenant_id=T,
        role_map=role_map if role_map is not None else {
            "boss@acme.test": "superadmin",
            "worker@acme.test": "member",
        },
        default_role=default_role,
    )
    return TestClient(create_app(asyncio.run(_kernel()), principal_resolver=resolver))


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_missing_assertion_rejected():
    # No CF header/cookie -> 401 (the edge should always inject it; absence is a
    # bypass attempt or a misconfigured origin).
    assert _client().get("/v1/capabilities").status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_unverifiable_assertion_rejected():
    r = _client().get("/v1/capabilities", headers={HDR: "forged"})
    assert r.status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_superadmin_gets_full_authority():
    # verified email boss@acme.test -> superadmin -> tenant-wide grants
    r = _client().get("/v1/capabilities", headers={HDR: "good.boss@acme.test"})
    assert r.status_code == 200
    ids = {v["id"] for v in r.json()["verbs"]}
    assert "ticket.create" in ids  # superadmin sees the tenant's verbs


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_member_can_operate_but_not_author():
    # member operates (sees/runs verbs) but the authoring routes are role-gated
    # (can_author=False), so configuration is denied - the admin/member boundary.
    c = _client()
    ok = c.get("/v1/capabilities", headers={HDR: "good.worker@acme.test"})
    assert ok.status_code == 200
    authoring = c.post(
        "/v1/nouns", headers={HDR: "good.worker@acme.test"}, json={"id": "x"}
    )
    assert authoring.status_code == 403  # member cannot author

    # a superadmin CAN author the same route
    admin_authoring = c.post(
        "/v1/nouns", headers={HDR: "good.boss@acme.test"}, json={"id": "x"}
    )
    assert admin_authoring.status_code in (200, 201)


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_authenticated_but_unmapped_email_is_denied():
    # A valid Access assertion for an email not in the role map is fail-closed
    # (default_role none), even though Access let it reach the origin - defence
    # in depth, so a widened Access policy can't silently grant kernel authority.
    r = _client().get("/v1/capabilities", headers={HDR: "good.stranger@acme.test"})
    assert r.status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_email_case_and_mapping_are_normalised():
    # The mapping is case-insensitive on the email; identity comes from the
    # verified claim, not any request-supplied value.
    r = _client(role_map={"Boss@Acme.test": "superadmin"}).get(
        "/v1/capabilities", headers={HDR: "good.BOSS@acme.test"}
    )
    assert r.status_code == 200
