"""Cross-tenant identity invariants ([2026] VJS-COUNTY 11): SEC-131..SEC-134.

One EMAIL is an identity that can belong to several orgs, authenticating ONCE
against a shared credential + 2FA held at the identity realm, then binding to
exactly ONE active org (tenant) per request. Isolation is paramount: a member of
org A can NEVER read org B's data; the org=tenant RLS fence stays intact.

  SEC-131  the resolver binds the request to the session's ACTIVE org and rebinds
           the RLS tenant to it every request (the principal's tenant IS the active
           org); a legacy / single-org identity is unchanged (backward-compatible).
  SEC-132  an org SWITCH is membership-RE-AUTHORIZED against org_members, fail-closed
           (404 unknown, 403 non-member, NO write), never trusts a client-supplied
           active org, and switching rebinds every subsequent read to the new org so
           no request ever reads more than one tenant (no cross-org read); a revoked
           membership drops the session fail-closed.
  SEC-133  a provisioned-org invitee (accept-invite provision_org) gets a USABLE login
           in the new org - a User row + org membership + the shared-credential
           association - so they can actually log in and switch into it.
  SEC-134  the shared credential + 2FA travel with the IDENTITY (the email), held
           ONCE at the identity realm (not duplicated per org) and sealed.

These exercise the REAL session resolver + HTTP surface, exactly as it faces the net.
"""

import asyncio
import json

import pyotp
import pytest
from fastapi.testclient import TestClient

from boltrig.identity import (
    build_session_resolver,
    hash_password,
    new_session,
    pick_default_org,
    resolve_active_org,
)
from boltrig.identity.sessions import SESSION_COOKIE
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    OrgMember,
    Organisation,
    TenantPermissions,
    User,
    UserSetting,
)
from boltrig.store import InMemoryStore
from tests.approval import approved_request
from boltrig.store.postgres import set_current_tenant

# The identity realm (the login realm) is also the founding org "default". "zorg" is a
# SECOND org the identity belongs to - named so "default" sorts first (the deterministic
# default active org is the realm), and the switch moves the request to "zorg".
REALM = "default"
ORG_B = "zorg"
OWNER = "owner@example.io"
OWNER_PW = "owner-password-123"
USER = "multi@example.io"
USER_PW = "multi-org-password-123"


def _run(coro):
    return asyncio.run(coro)


def _app():
    store = InMemoryStore()
    for tid in (REALM, ORG_B):
        store.set_tenant_permissions(TenantPermissions(tid, GrantSet.of(["*"])))
    k = Kernel(store)
    app = create_app(k, principal_resolver=build_session_resolver(REALM), platform={})
    return k, app, store


async def _seat_multi_org(store):
    """Seat ONE identity (USER) as a member of the realm org AND org B, with the shared
    credential held ONCE at the realm and a distinct per-org setting in each org."""
    # The shared credential is held ONCE at the identity realm (keyed by the email).
    await store.set_password_credential(REALM, USER, hash_password(USER_PW))
    for tid, role in ((REALM, "admin"), (ORG_B, "author")):
        await store.create_org(Organisation(id=tid, name=tid, slug=tid))
        # A PER-ORG User row (D1): the identity's role/scope in that org.
        await store.upsert_user(User(
            id=USER, tenant_id=tid, email=USER, role=role, scope={},
            status="active", source="invitation",
        ))
        # add_org_member also writes the global email -> orgs index pointer.
        await store.add_org_member(OrgMember(user_id=USER, tenant_id=tid, role=role))
        # A tenant-scoped datum whose value names its org, so a cross-org read shows up.
        await store.upsert_user_setting(UserSetting(
            tenant_id=tid, user_id=USER, key="home", value=f"secret-of-{tid}",
        ))


def _set_cookies_insecure(monkeypatch):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")


def _login(client, email=USER, password=USER_PW):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


class _FakeRequest:
    """A minimal Request the resolver can read (cookie + app + method) so a test can
    observe the Principal it builds without an HTTP round-trip."""

    def __init__(self, app, secret, *, method="GET"):
        from types import SimpleNamespace

        self.app = app
        self.cookies = {SESSION_COOKIE: secret}
        self.method = method
        self.headers = {}
        self.state = SimpleNamespace()


# --- SEC-131: the resolver binds + rebinds RLS to the session's active org ----------
@pytest.mark.security
@pytest.mark.invariant("SEC-131")
def test_resolver_binds_the_request_to_the_session_active_org(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_multi_org(store))
    resolver = build_session_resolver(REALM)

    # A session whose active org is ORG_B: the principal's tenant IS ORG_B (not the
    # realm the session lives at), and the RLS tenant is rebound to ORG_B for the
    # request - so the principal carries the identity's PER-ORG role in ORG_B (author).
    session, secret, _csrf = new_session(REALM, USER, client="web")
    session.active_org_id = ORG_B
    _run(store.add_session(session))
    set_current_tenant(None)
    principal = _run(resolver(_FakeRequest(app, secret)))
    # The principal's tenant IS ORG_B, and its role is the ORG_B per-org row (author) -
    # which the resolver could only read by REBINDING the tenant to ORG_B before the
    # per-org identity read. That is the request-bound rebind (the RLS tenant for the
    # rest of the request), proven through the principal the kernel actually receives.
    assert principal.tenant_id == ORG_B          # bound to the active org, not the realm
    assert principal.subject == USER
    assert principal.role == "author"            # the PER-ORG identity row in ORG_B

    # The SAME identity with active org = the realm resolves to the realm + its role.
    s2, secret2, _c2 = new_session(REALM, USER, client="web")
    s2.active_org_id = REALM
    _run(store.add_session(s2))
    p2 = _run(resolver(_FakeRequest(app, secret2)))
    assert p2.tenant_id == REALM and p2.role == "admin"

    # Backward-compat: a LEGACY identity with NO membership-index rows resolves to the
    # session's own tenant exactly as before (a single-org console is unchanged).
    legacy_store = InMemoryStore()
    _run(legacy_store.set_password_credential(REALM, OWNER, hash_password(OWNER_PW)))
    _run(legacy_store.upsert_user(User(
        id=OWNER, tenant_id=REALM, email=OWNER, role="superadmin",
        scope={"all": True}, status="active", source="initiate",
    )))
    legacy_app = create_app(Kernel(legacy_store),
                            principal_resolver=build_session_resolver(REALM), platform={})
    ls, lsecret, _lc = new_session(REALM, OWNER, client="web")
    _run(legacy_store.add_session(ls))
    lp = _run(build_session_resolver(REALM)(_FakeRequest(legacy_app, lsecret)))
    assert lp.tenant_id == REALM   # no index -> the realm, unchanged
    set_current_tenant(None)


# --- SEC-132: the org switch is membership-re-authorized + no cross-org read --------
@pytest.mark.security
@pytest.mark.invariant("SEC-132")
def test_org_switch_is_reauthorized_and_no_cross_org_read(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_multi_org(store))
    # A THIRD org the USER is NOT a member of (exists, but no membership).
    _run(store.create_org(Organisation(id="foreign", name="foreign", slug="foreign")))

    c = TestClient(app)
    csrf = _login(c).json()["csrf_token"]
    hdr = {"x-boltrig-csrf": csrf}

    # The deterministic default active org is the realm; the request reads ONLY the
    # realm's datum, never ORG_B's (one active tenant per request, no cross-org read).
    s1 = c.get("/v1/me/settings").json()
    assert s1["settings"]["home"] == f"secret-of-{REALM}"
    assert f"secret-of-{ORG_B}" not in json.dumps(s1)

    # Unknown org -> 404, NO write. Non-member org (exists) -> 403, NO write. A
    # client-supplied active org the caller is not a member of is NEVER trusted.
    assert c.post("/v1/me/active-org", json={"org_id": "nope"}, headers=hdr).status_code == 404
    assert c.post("/v1/me/active-org", json={"org_id": "foreign"}, headers=hdr).status_code == 403
    assert c.post("/v1/me/active-org", json={}, headers=hdr).status_code == 400
    # After the refused switches the request is STILL bound to the realm (no leak).
    assert c.get("/v1/me/settings").json()["settings"]["home"] == f"secret-of-{REALM}"

    # A member switch to ORG_B is re-authorized + persists; EVERY subsequent read is
    # now bound to ORG_B and can never see the realm's datum (the switch is the only
    # tenant change; no request reads more than one tenant).
    ok = c.post("/v1/me/active-org", json={"org_id": ORG_B}, headers=hdr)
    assert ok.status_code == 200 and ok.json()["org_id"] == ORG_B
    s2 = c.get("/v1/me/settings").json()
    assert s2["settings"]["home"] == f"secret-of-{ORG_B}"
    assert f"secret-of-{REALM}" not in json.dumps(s2)

    # Session management stays correct across the switch: sessions live at the identity
    # realm, so the panel still lists + can manage this session while the request is
    # bound to ORG_B (it is not scoped to the active org, which would return nothing).
    panel = c.get("/v1/me/sessions")
    assert panel.status_code == 200 and len(panel.json()["sessions"]) >= 1

    # Revoke the ORG_B membership: the session (still pinned to ORG_B) drops fail-closed
    # on its next request - it can NEVER keep ORG_B's access. The identity is still a
    # member of the realm, so the request re-binds DOWN to the realm (its remaining
    # membership), never staying on the revoked org and never reading ORG_B again.
    _run(store.remove_org_member(ORG_B, USER))
    s3 = c.get("/v1/me/settings")
    assert s3.status_code == 200
    assert s3.json()["settings"]["home"] == f"secret-of-{REALM}"
    assert f"secret-of-{ORG_B}" not in json.dumps(s3.json())

    # Revoke the LAST remaining membership too: with no membership surviving, the
    # membership-model session dies fail-closed (it must never fall back to realm
    # access after losing every org it belonged to).
    _run(store.remove_org_member(REALM, USER))
    assert c.get("/v1/me/settings").status_code == 401


# --- SEC-133: a provisioned-org invitee gets a usable login in the new org ----------
@pytest.mark.security
@pytest.mark.invariant("SEC-133")
def test_provisioned_org_invitee_gets_a_usable_login(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    # The owner (superadmin) at the realm mints a provision_org invite (owner-only).
    _run(store.upsert_user(User(
        id=OWNER, tenant_id=REALM, email=OWNER, role="superadmin",
        scope={"all": True}, status="active", source="initiate",
    )))
    _run(store.set_password_credential(REALM, OWNER, hash_password(OWNER_PW)))
    owner_c = TestClient(app)
    csrf = _login(owner_c, OWNER, OWNER_PW).json()["csrf_token"]
    invite_body = {"email": "founder@newco.io", "role": "member",
                   "provision_org_name": "NewCo"}
    inv = approved_request(
        owner_c,
        k,
        REALM,
        "POST",
        "/v1/admin/invitations",
        json=invite_body,
        headers={"x-boltrig-csrf": csrf},
    )
    assert inv.status_code == 200, inv.text
    token = inv.json()["invite_token"]

    # The invitee accepts + sets a password: this must materialise a USABLE login in
    # the freshly provisioned org (before this fix, accept created only an OrgMember).
    invitee_c = TestClient(app)
    ac = invitee_c.post("/v1/auth/accept-invite",
                        json={"token": token, "password": "founder-password-123"})
    assert ac.status_code == 200, ac.text

    # The new org was provisioned, and the invitee got a User row + membership in it +
    # the shared credential (held once at the realm) - the three parts of a login.
    new_tid = next(
        t for t, o in store._orgs.items() if o.name == "NewCo"
    )
    assert (new_user := _run(store.get_user(new_tid, "founder@newco.io"))) is not None
    assert new_user.role == "superadmin"                       # owner of their own org
    assert _run(store.get_org_member(new_tid, "founder@newco.io")) is not None
    assert new_tid in _run(store.list_orgs_for_email("founder@newco.io"))
    assert _run(store.get_password_credential(REALM, "founder@newco.io")) is not None

    # And they can ACTUALLY log in and reach the console bound to the new org.
    assert _login(invitee_c, "founder@newco.io", "founder-password-123").status_code == 200
    me = invitee_c.get("/v1/me/settings")
    assert me.status_code == 200
    # The active org is the provisioned org (their only membership), so the profile the
    # console returns is their superadmin identity IN the new org.
    assert me.json()["profile"]["role"] == "superadmin"


# --- SEC-134: the shared credential + 2FA travel with the identity, held once -------
@pytest.mark.security
@pytest.mark.invariant("SEC-134")
def test_shared_credential_and_2fa_travel_with_the_identity(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_multi_org(store))

    # The shared credential is held ONCE at the identity realm, keyed by the email -
    # NOT duplicated into the per-org rows (ORG_B has no credential of its own).
    assert _run(store.get_password_credential(REALM, USER)) is not None
    assert _run(store.get_password_credential(ORG_B, USER)) is None

    # The email -> orgs index is a pre-tenant lookup that holds only membership
    # POINTERS (tenant_ids) - never a secret and never business data.
    orgs = _run(store.list_orgs_for_email(USER))
    assert set(orgs) == {REALM, ORG_B}
    assert USER_PW not in json.dumps(orgs)

    # The ONE shared credential authenticates the identity regardless of which org it
    # ends up bound to (a single login works; the active org is chosen after auth).
    c = TestClient(app)
    assert _login(c).status_code == 200

    # 2FA travels with the IDENTITY (the realm), not the per-org row: enroll once, and
    # the sealed secret + enrolment live at the realm keyed by the email, with NO totp
    # row in ORG_B. The secret is SEALED (only a ref on the row; the value in the
    # credential store), never a plaintext column.
    csrf = _login(c).json()["csrf_token"]
    begin = c.post("/v1/auth/2fa/enroll", headers={"x-boltrig-csrf": csrf})
    assert begin.status_code == 200, begin.text
    secret = begin.json()["secret"]
    code = pyotp.TOTP(secret).now()
    assert c.post("/v1/auth/2fa/verify-enroll", json={"code": code},
                  headers={"x-boltrig-csrf": csrf}).status_code == 200

    totp = _run(store.get_user_totp(REALM, USER))          # at the identity realm
    assert totp is not None and totp.enrolled is True
    assert _run(store.get_user_totp(ORG_B, USER)) is None  # never on the per-org row
    assert totp.secret_ref and totp.secret_ref != secret   # sealed: a ref, not the secret
    assert _run(store.get_credential_ref(REALM, totp.secret_ref)) == {"secret": secret}


# --- helper-level checks: the store index + pick_default_org (unit) -----------------
@pytest.mark.security
@pytest.mark.invariant("SEC-131")
def test_active_org_resolution_and_index_helpers():
    store = InMemoryStore()

    # pick_default_org is deterministic (smallest id) or None for a legacy identity.
    assert pick_default_org([]) is None
    assert pick_default_org([ORG_B, REALM]) == REALM

    # The index is kept in lockstep with org_members: add records, remove drops it, and
    # get_org_member is the tenant-scoped re-auth (None outside the bound tenant).
    _run(store.add_org_member(OrgMember(user_id=USER, tenant_id=REALM, role="admin")))
    _run(store.add_org_member(OrgMember(user_id=USER, tenant_id=ORG_B, role="author")))
    assert set(_run(store.list_orgs_for_email(USER))) == {REALM, ORG_B}
    assert _run(store.get_org_member(REALM, USER)).role == "admin"
    assert _run(store.get_org_member("unbound", USER)) is None    # fail-closed

    # resolve_active_org honours a still-valid hint, else picks a member deterministically.
    sess, _s, _c = new_session(REALM, USER, client="web")
    sess.active_org_id = ORG_B
    assert _run(resolve_active_org(store, REALM, sess, USER)) == ORG_B
    sess.active_org_id = None
    assert _run(resolve_active_org(store, REALM, sess, USER)) == REALM   # smallest member

    # A revoked membership is dropped from the index and can never be resolved to.
    _run(store.remove_org_member(ORG_B, USER))
    assert _run(store.list_orgs_for_email(USER)) == [REALM]
    sess.active_org_id = ORG_B                         # stale client hint
    assert _run(resolve_active_org(store, REALM, sess, USER)) == REALM   # never trusts it
    set_current_tenant(None)
