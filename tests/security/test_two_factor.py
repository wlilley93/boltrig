"""TOTP two-factor + one-time recovery-code invariants ([2026] VJS-COUNTY 10):
SEC-126..SEC-130.

The console second factor, exercised through the REAL HTTP surface behind the
session principal resolver (exactly as it faces the internet):

  SEC-126  the TOTP secret is SEALED (credential store), never a plaintext column,
           never audited, never returned after enrollment.
  SEC-127  recovery codes are stored only as hashes, single-use, a FALLBACK - never
           a bypass and never reusable.
  SEC-128  the challenge sits BETWEEN password-verify and session-issue and is
           fail-closed: an enrolled user gets NO session until a factor verifies.
  SEC-129  an org that requires 2FA FORCES enrollment - an unenrolled user reaches
           ONLY the enrollment surface, nothing else.
  SEC-130  the challenge is rate-limited, constant-time / non-enumerating, and
           audited (enroll / challenge-pass / challenge-fail / recovery-use).

An org that does NOT require 2FA and a user with no factor log in EXACTLY as
before (the backward-compat path is covered by test_first_party_login.py, which
stays green).
"""

import asyncio
import json

import pyotp
import pytest
from fastapi.testclient import TestClient

from boltrig.identity import build_session_resolver, hash_password
from boltrig.identity.totp import hash_recovery_code, normalize_recovery_code
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, Organisation, TenantPermissions, User
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed

T = "default"
OWNER = "owner@example.io"
OWNER_PW = "owner-password-123"


def _run(coro):
    return asyncio.run(coro)


def _app():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    app = create_app(k, principal_resolver=build_session_resolver(T), platform={})
    return k, app, store


async def _seat_owner(store, *, require_2fa=False):
    await store.upsert_user(User(
        id=OWNER, tenant_id=T, email=OWNER, role="superadmin",
        scope={"all": True}, status="active", source="initiate",
    ))
    await store.set_password_credential(T, OWNER, hash_password(OWNER_PW))
    if require_2fa:
        await store.create_org(Organisation(
            id=T, name="Console", slug="console", require_two_factor=True,
        ))


def _set_cookies_insecure(monkeypatch):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")


def _login(client, email=OWNER, password=OWNER_PW):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def _enroll(client, csrf):
    """Begin + confirm a TOTP enrollment; returns (secret, recovery_codes)."""
    begin = client.post("/v1/auth/2fa/enroll", headers={"x-boltrig-csrf": csrf})
    assert begin.status_code == 200, begin.text
    body = begin.json()
    secret = body["secret"]
    codes = body["recovery_codes"]
    code = pyotp.TOTP(secret).now()
    ok = client.post("/v1/auth/2fa/verify-enroll", json={"code": code},
                     headers={"x-boltrig-csrf": csrf})
    assert ok.status_code == 200, ok.text
    return secret, codes


# --- SEC-126: the TOTP secret is sealed, never plaintext/audited/returned --------
@pytest.mark.security
@pytest.mark.invariant("SEC-126")
def test_totp_secret_is_sealed_never_plaintext_or_audited(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    c = TestClient(app)
    csrf = _login(c).json()["csrf_token"]
    secret, _codes = _enroll(c, csrf)

    # The enrolment row carries only a SEALED reference, never the secret itself.
    totp = _run(store.get_user_totp(T, OWNER))
    assert totp is not None and totp.enrolled is True
    assert totp.secret_ref and totp.secret_ref != secret
    assert secret not in json.dumps(totp.__dict__, default=str)

    # The secret lives in the RLS-fenced credential store (the sealed seam), and
    # there is no plaintext secret column on the identity row.
    ref = _run(store.get_credential_ref(T, totp.secret_ref))
    assert ref == {"secret": secret}
    # At rest the row is a sealed envelope (SEC-169) - the base32 secret never
    # rests in the store as plaintext.
    raw = store._creds[(T, totp.secret_ref)]
    assert is_sealed(raw) and secret not in json.dumps(raw)
    user = _run(store.get_user(T, OWNER))
    assert secret not in json.dumps(user.__dict__, default=str)

    # The secret never enters the audit chain (keys-only, K-20).
    events = _run(store.audit_query(T, limit=1000))
    blob = json.dumps([e.detail for e in events], default=str)
    assert secret not in blob
    # And there is no route that returns the secret again after enrollment.
    again = c.post("/v1/auth/2fa/enroll", headers={"x-boltrig-csrf": csrf})
    assert again.status_code == 400  # already enabled; no re-reveal


# --- SEC-127: recovery codes hashed + single-use, a fallback not a bypass --------
@pytest.mark.security
@pytest.mark.invariant("SEC-127")
def test_recovery_codes_are_hashed_and_single_use(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    enroller = TestClient(app)
    csrf = _login(enroller).json()["csrf_token"]
    _secret, codes = _enroll(enroller, csrf)
    assert len(codes) == 10

    # Stored ONLY as hashes: the plaintext codes are nowhere in the store, and the
    # stored count matches; the persisted form equals the sha256 of the code.
    assert store._recovery[(T, OWNER)]  # exists
    for code in codes:
        assert hash_recovery_code(code) in store._recovery[(T, OWNER)]
        assert normalize_recovery_code(code) not in json.dumps(
            store._recovery[(T, OWNER)], default=str
        )
    assert _run(store.count_active_recovery_codes(T, OWNER)) == 10

    # A recovery code is a FALLBACK for the second factor at the login challenge -
    # it passes ONCE, then the SAME code is rejected (single-use), and it never
    # bypasses the challenge (a fresh login still returns 2fa_required first).
    c = TestClient(app)
    first = _login(c)
    assert first.json()["status"] == "2fa_required"
    challenge = first.json()["challenge_token"]
    used = codes[0]
    ok = c.post("/v1/auth/2fa/challenge",
                json={"challenge_token": challenge, "code": used})
    assert ok.status_code == 200 and ok.json()["status"] == "ok"
    assert c.get("/v1/me/sessions").status_code == 200  # session now issued

    # The consumed code cannot be reused on a new challenge.
    c2 = TestClient(app)
    ch2 = _login(c2).json()["challenge_token"]
    replay = c2.post("/v1/auth/2fa/challenge",
                     json={"challenge_token": ch2, "code": used})
    assert replay.status_code == 401
    assert _run(store.count_active_recovery_codes(T, OWNER)) == 9
    # Recovery codes never enter the audit chain.
    events = _run(store.audit_query(T, limit=1000))
    blob = json.dumps([e.detail for e in events], default=str)
    for code in codes:
        assert normalize_recovery_code(code) not in blob


# --- SEC-128: the challenge is fail-closed, between password and session ---------
@pytest.mark.security
@pytest.mark.invariant("SEC-128")
def test_challenge_is_fail_closed_between_password_and_session(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    enroller = TestClient(app)
    csrf = _login(enroller).json()["csrf_token"]
    secret, _codes = _enroll(enroller, csrf)

    # A fresh, correct password login for an enrolled user returns 2fa_required and
    # NO session: the httpOnly session cookie is NOT set, and an authed route 401s.
    c = TestClient(app)
    res = _login(c)
    assert res.status_code == 200 and res.json()["status"] == "2fa_required"
    set_cookies = [v for kk, v in res.headers.multi_items() if kk.lower() == "set-cookie"]
    assert not any(sc.startswith("boltrig_session=") for sc in set_cookies)
    assert c.get("/v1/me/sessions").status_code == 401  # no session yet (fail-closed)
    challenge = res.json()["challenge_token"]

    # A wrong code does NOT issue a session.
    bad = c.post("/v1/auth/2fa/challenge",
                 json={"challenge_token": challenge, "code": "000000"})
    assert bad.status_code == 401
    assert c.get("/v1/me/sessions").status_code == 401

    # The correct TOTP code issues the session (challenge -> session).
    good = c.post("/v1/auth/2fa/challenge",
                  json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()})
    assert good.status_code == 200 and good.json()["status"] == "ok"
    assert c.get("/v1/me/sessions").status_code == 200

    # The challenge is single-use: it cannot be replayed for a second session.
    replay = TestClient(app).post("/v1/auth/2fa/challenge",
                                  json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()})
    assert replay.status_code == 401

    # An unknown challenge token is a generic, fail-closed rejection.
    unknown = TestClient(app).post("/v1/auth/2fa/challenge",
                                   json={"challenge_token": "boltrig_2fa_nope", "code": "123456"})
    assert unknown.status_code == 401


# --- SEC-129: org require_two_factor forces enrollment-only ---------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-129")
def test_org_required_two_factor_forces_enrollment_only(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store, require_2fa=True))

    # The org requires 2FA and the user has not enrolled: login does NOT grant
    # console access; it returns 2fa_enrollment_required.
    c = TestClient(app)
    res = _login(c)
    assert res.status_code == 200 and res.json()["status"] == "2fa_enrollment_required"
    csrf = res.json()["csrf_token"]

    # The session it carries is CLAMPED to enrollment only: every non-enroll authed
    # route is refused with the distinct enrollment marker; enroll routes are open.
    blocked = c.get("/v1/me/sessions")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "two_factor_enrollment_required"
    # Enrollment surface reachable.
    secret, _codes = _enroll(c, csrf)
    # Once enrolled, the SAME session reaches the console (clamp lifts).
    assert c.get("/v1/me/sessions").status_code == 200

    # Mid-session policy flip: a user who logged in BEFORE the requirement is
    # clamped on their next request once the org flips it on and they are unenrolled.
    k2, app2, store2 = _app()
    _run(_seat_owner(store2))  # no requirement yet
    c2 = TestClient(app2)
    assert _login(c2).json()["status"] == "ok"
    assert c2.get("/v1/me/sessions").status_code == 200
    _run(store2.create_org(Organisation(
        id=T, name="Console", slug="console", require_two_factor=True,
    )))
    clamped = c2.get("/v1/me/sessions")
    assert clamped.status_code == 403
    assert clamped.json()["detail"] == "two_factor_enrollment_required"


# --- SEC-130: the challenge is rate-limited, constant-time, audited -------------
@pytest.mark.security
@pytest.mark.invariant("SEC-130")
def test_challenge_is_rate_limited_constant_time_and_audited(monkeypatch):
    _set_cookies_insecure(monkeypatch)

    # Non-enumeration / constant-time: an unknown challenge and a valid challenge
    # with a wrong code return the BYTE-IDENTICAL generic failure + status.
    k, app, store = _app()
    _run(_seat_owner(store))
    enroller = TestClient(app)
    csrf = _login(enroller).json()["csrf_token"]
    _enroll(enroller, csrf)
    challenge = _login(TestClient(app)).json()["challenge_token"]
    unknown = app_post(app, "boltrig_2fa_unknown", "000000")
    wrong = app_post(app, challenge, "111111")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()

    # A failed challenge is AUDITED (keys-only) and raises a SecurityEvent signal.
    events = _run(store.audit_query(T, limit=1000))
    assert any(e.verb == "auth.2fa.challenge" and e.status == "denied" for e in events)
    signals = _run(store.security_query(T))
    assert any(s.reason == "two_factor_challenge_failed" for s in signals)
    # The enroll begin + activate are audited too (keys-only).
    assert any(e.verb == "auth.2fa.enroll" for e in events)
    assert any(e.verb == "auth.2fa.verify_enroll" and e.status != "denied" for e in events)

    # Rate limit: the per-identity bound (5/min) trips on the 6th wrong attempt with
    # 429. A miss does NOT consume the challenge, so the same token stays usable.
    k2, app2, store2 = _app()
    _run(_seat_owner(store2))
    e2 = TestClient(app2)
    csrf2 = _login(e2).json()["csrf_token"]
    _enroll(e2, csrf2)
    ch = _login(TestClient(app2)).json()["challenge_token"]
    codes = [app_post(app2, ch, "222222").status_code for _ in range(6)]
    assert codes[:5] == [401, 401, 401, 401, 401]
    assert codes[5] == 429


def app_post(app, challenge_token, code):
    return TestClient(app).post(
        "/v1/auth/2fa/challenge",
        json={"challenge_token": challenge_token, "code": code},
    )
