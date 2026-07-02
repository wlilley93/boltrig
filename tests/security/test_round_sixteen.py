"""Round Sixteen - security hardening, the buildable kernel-side controls.

Binds the genuinely-missing code controls from the Batch 1/2 specs:
  SEC-58  edge/web hardening: security headers on every response, Host validation,
          request-body cap (WEB-02/03/06, RES-01).
  SEC-59  JWT verification pins an algorithm allowlist, rejects an ID token used as
          an access token, and rejects a token with no expiry (IAM-02/03/04).
  SEC-60  dev auth refuses to start with a production signal (IAM-09).
  SEC-61  the shared egress guard blocks cloud-metadata / link-local targets for
          every HTTP adapter, not just web.fetch (INJ-02 / CLOUD-03).
  SEC-62  a Unicode-confusable / non-canonical verb id can never match a grant
          (UPLOAD-05 / AZ-02).
  SEC-63  an inbound webhook outside the replay window is rejected (ADP-08).
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.inbound_webhook import WebhookAuthError, verify_and_normalise
from boltrig.adapters.egress import (
    EgressBlocked,
    assert_egress_allowed,
    assert_no_metadata_egress,
    is_blocked_ip,
    is_metadata_ip,
)
from boltrig.api.bootstrap import production_signal, refuse_dev_auth_in_prod
from boltrig.models.grants import GrantSet, is_safe_identifier
from boltrig.kernel.web_security import install_security


# --------------------------------------------------------------------------- #
# SEC-58  edge/web hardening
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-58")
def test_security_headers_host_and_body_cap():
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/echo")
    def echo(body: dict):
        return body

    install_security(app, env={"BOLTRIG_ALLOWED_HOSTS": "testserver", "BOLTRIG_MAX_BODY_BYTES": "100"})
    c = TestClient(app)

    r = c.get("/ping")
    assert r.status_code == 200
    # security headers present on every response (WEB-02/03)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" in r.headers
    assert "content-security-policy" in r.headers

    # body-size cap returns 413 (RES-01)
    big = c.post("/echo", content=b"x" * 200, headers={"content-type": "application/json"})
    assert big.status_code == 413

    # Host validation (WEB-06): an unlisted Host is refused
    bad = c.get("/ping", headers={"host": "evil.example"})
    assert bad.status_code == 400


# --------------------------------------------------------------------------- #
# SEC-59  JWT verification hardening (IAM-02/03/04)
# --------------------------------------------------------------------------- #
def _have_authlib() -> bool:
    try:
        import authlib.jose  # noqa: F401
        import cryptography  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.security
@pytest.mark.invariant("SEC-59")
@pytest.mark.skipif(not _have_authlib(), reason="authlib + cryptography required")
async def test_jwt_alg_allowlist_and_access_token_only():
    from authlib.jose import JsonWebKey, jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from boltrig.identity.auth import OidcVerifier

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        __import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
        __import__("cryptography").hazmat.primitives.serialization.PrivateFormat.PKCS8,
        __import__("cryptography").hazmat.primitives.serialization.NoEncryption(),
    )
    jwk = JsonWebKey.import_key(key.public_key(), {"kty": "RSA", "use": "sig", "kid": "k1"})
    v = OidcVerifier("https://idp", "boltrig", "https://idp/jwks")
    v._jwks = {"keys": [jwk.as_dict()]}
    v._jwks_at = time.monotonic()

    now = int(time.time())
    base = {"iss": "https://idp", "aud": "boltrig", "sub": "u", "iat": now, "exp": now + 600}

    def sign(claims):
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, priv_pem).decode()

    # a valid RS256 access token verifies (alg is on the allowlist)
    assert (await v.verify(sign(base)))["sub"] == "u"
    # an ID token presented as an access token is rejected (IAM-04)
    with pytest.raises(Exception):
        await v.verify(sign({**base, "token_use": "id"}))
    # a token with no expiry is rejected (IAM-03)
    with pytest.raises(Exception):
        await v.verify(sign({k: val for k, val in base.items() if k != "exp"}))


# --------------------------------------------------------------------------- #
# SEC-60  dev auth impossible in production (IAM-09)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-60")
def test_dev_auth_refuses_production_signal():
    assert production_signal({"ENV": "production"}) is not None
    assert production_signal({"BOLTRIG_PRODUCTION": "1"}) is not None
    assert production_signal({"ENV": "dev"}) is None
    # a prod signal makes dev auth a fatal start error
    with pytest.raises(RuntimeError):
        refuse_dev_auth_in_prod({"ENV": "prod"})
    refuse_dev_auth_in_prod({"ENV": "dev"})  # no signal -> no raise

    # K-19: an unset/default audit HMAC key in prod is also fatal (forgeable chain)
    from boltrig.api.bootstrap import refuse_default_audit_key_in_prod

    with pytest.raises(RuntimeError):
        refuse_default_audit_key_in_prod({"ENV": "prod"})
    with pytest.raises(RuntimeError):
        refuse_default_audit_key_in_prod({"ENV": "prod", "BOLTRIG_AUDIT_HMAC_KEY": "dev-insecure-audit-key"})
    refuse_default_audit_key_in_prod({"ENV": "prod", "BOLTRIG_AUDIT_HMAC_KEY": "a-real-secret"})  # ok
    refuse_default_audit_key_in_prod({"ENV": "dev"})  # no signal -> ok

    # SEC-60 at the dangerous default: create_app() with a prod signal and no
    # resolver refuses to fall back to header-trust auth.
    import os

    from boltrig.kernel import Kernel
    from boltrig.kernel.app import create_app
    from boltrig.store import InMemoryStore

    os.environ["BOLTRIG_PRODUCTION"] = "1"
    try:
        with pytest.raises(RuntimeError):
            create_app(Kernel(InMemoryStore()), platform={})
    finally:
        del os.environ["BOLTRIG_PRODUCTION"]


# --------------------------------------------------------------------------- #
# K-19  audit-key guard on every kernel-building path (H3)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("K-19")
async def test_worker_boot_refuses_default_audit_key_under_prod_signal(monkeypatch):
    # H3: build_kernel_async is the path the fleet + Hatchet workers boot through
    # (not create_app). Under a production signal with no audit HMAC key it must
    # refuse to boot, so no worker writes forgeable audit rows under the in-source
    # default. With a real key it boots.
    from boltrig.api.bootstrap import build_kernel_async

    monkeypatch.setenv("BOLTRIG_PRODUCTION", "1")
    monkeypatch.delenv("BOLTRIG_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)  # stay offline (in-memory store)
    monkeypatch.delenv("BOLTRIG_MANIFEST", raising=False)
    with pytest.raises(RuntimeError):
        await build_kernel_async()

    monkeypatch.setenv("BOLTRIG_AUDIT_HMAC_KEY", "a-real-secret")
    kernel = await build_kernel_async()
    assert kernel is not None


# --------------------------------------------------------------------------- #
# SEC-61  shared egress guard blocks metadata/link-local for any adapter
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-61")
def test_shared_egress_guard_blocks_metadata():
    assert is_metadata_ip("169.254.169.254") is True   # cloud IMDS
    assert is_metadata_ip("169.254.10.1") is True       # link-local
    assert is_metadata_ip("93.184.216.34") is False     # public
    # an IP-literal metadata URL is refused before any network call
    with pytest.raises(EgressBlocked):
        assert_no_metadata_egress("http://169.254.169.254/latest/meta-data/")
    # a public target is allowed through the metadata guard
    assert_no_metadata_egress("https://93.184.216.34/")

    # The FULL guard (used by http_base + the MCP consumer, which also set
    # follow_redirects=False) blocks private/loopback/reserved too - so a 302 into
    # internal space or a mis-set internal target is refused, not just metadata.
    assert is_blocked_ip("127.0.0.1") and is_blocked_ip("10.0.0.1")
    assert is_blocked_ip("192.168.1.5") and is_blocked_ip("169.254.169.254")
    assert is_blocked_ip("93.184.216.34") is False  # public ok
    with pytest.raises(EgressBlocked):
        assert_egress_allowed("http://127.0.0.1/internal")
    with pytest.raises(EgressBlocked):
        assert_egress_allowed("http://10.0.0.5/admin")
    assert_egress_allowed("https://93.184.216.34/")  # public still allowed


# --------------------------------------------------------------------------- #
# SEC-62  confusable verb id cannot bypass a grant (UPLOAD-05 / AZ-02)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-62")
def test_confusable_verb_id_never_matches_a_grant():
    g = GrantSet.of(["ticket.*", "ticket.create"])
    assert g.permits("ticket.create") is True  # the real ASCII verb
    # a Cyrillic-'a' homoglyph of "ticket.create" must NOT be authorised
    confusable = "ticket.creаte"  # а is Cyrillic 'а'
    assert is_safe_identifier(confusable) is False
    assert g.permits(confusable) is False
    # a zero-width-joiner trick is also not safe and not authorised
    assert g.permits("ticket.cre‍ate") is False


# --------------------------------------------------------------------------- #
# SEC-63  webhook replay window (ADP-08)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-63")
def test_webhook_replay_window():
    from boltrig.adapters.builtin.inbound_webhook import (
        canonical_body,
        expected_signature,
        signed_content,
    )

    secret = "whsec"
    payload = {"type": "issue.opened", "id": "e1"}
    fresh = int(time.time())
    # the timestamp is bound into the signed content (M3/SEC-66); a fresh, signed
    # request with a current timestamp is accepted
    sig = expected_signature(secret, signed_content(fresh, canonical_body(payload)))
    ok = verify_and_normalise(payload, {"x-signature": f"t={fresh},v1={sig}"},
                              secret, now=fresh)
    assert ok["authenticated"] is True
    # a captured request whose (bound) timestamp is far in the past is rejected as
    # a replay: sign at the stale time, then present it now.
    stale = fresh - 10_000
    stale_sig = expected_signature(secret, signed_content(stale, canonical_body(payload)))
    with pytest.raises(WebhookAuthError):
        verify_and_normalise(
            payload, {"x-signature": f"t={stale},v1={stale_sig}"},
            secret, now=fresh,
        )
