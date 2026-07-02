"""Real authentication: bearer verification + scoped principal (SEC-01, US-IAM-01/02).

The stub-verifier tests prove the resolver contract offline (no IdP, no authlib):
an invalid/missing bearer is rejected 401 and a valid token yields a
correctly-scoped principal. The OidcVerifier round-trip proves real RS256 JWT
verification when authlib + cryptography are present.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.identity.auth import build_principal_resolver
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, RoleMapping, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


class _StubVerifier:
    """Accepts the literal token 'good', rejects everything else."""

    async def verify(self, token: str) -> dict:
        if token != "good":
            raise ValueError("bad token")
        return {"sub": "alice", "groups": ["Engineering"]}


async def _kernel() -> Kernel:
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _client() -> TestClient:
    import asyncio

    mappings = [
        RoleMapping(
            tenant_id=T, idp_group="Engineering", role="engineer",
            scope={"departments": ["engineering"], "verbs": ["ticket.read"]},
        )
    ]
    resolver = build_principal_resolver(verifier=_StubVerifier(), mappings=mappings, tenant_id=T)
    return TestClient(create_app(asyncio.run(_kernel()), principal_resolver=resolver))


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_missing_bearer_rejected():
    assert _client().get("/v1/capabilities").status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_invalid_bearer_rejected():
    r = _client().get("/v1/capabilities", headers={"authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_valid_bearer_yields_scoped_principal():
    # token verified -> groups -> role engineer -> scope -> grants ["ticket.read"]
    r = _client().get("/v1/capabilities", headers={"authorization": "Bearer good"})
    assert r.status_code == 200
    ids = {v["id"] for v in r.json()["verbs"]}
    assert "ticket.read" in ids and "ticket.create" not in ids  # scoped by the token


# --- real RS256 verification (authlib), skipped if the crypto stack is absent --
def _have_authlib() -> bool:
    try:
        import authlib.jose  # noqa: F401
        import cryptography  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.security
@pytest.mark.skipif(not _have_authlib(), reason="authlib + cryptography required")
async def test_oidc_verifier_accepts_valid_and_rejects_wrong_audience():
    from authlib.jose import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from boltrig.identity.auth import OidcVerifier

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        __import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
        __import__("cryptography").hazmat.primitives.serialization.PrivateFormat.PKCS8,
        __import__("cryptography").hazmat.primitives.serialization.NoEncryption(),
    )
    from authlib.jose import JsonWebKey

    jwk = JsonWebKey.import_key(key.public_key(), {"kty": "RSA", "use": "sig", "kid": "k1"})
    jwks = {"keys": [jwk.as_dict()]}

    issuer, audience = "https://idp.example", "boltrig"
    header = {"alg": "RS256", "kid": "k1"}

    import time

    good = jwt.encode(
        header, {"iss": issuer, "aud": audience, "sub": "bob", "exp": int(time.time()) + 300},
        priv_pem,
    ).decode()
    wrong_aud = jwt.encode(
        header, {"iss": issuer, "aud": "other", "sub": "bob", "exp": int(time.time()) + 300},
        priv_pem,
    ).decode()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return jwks

    class _Http:
        async def get(self, url):
            return _Resp()

    v = OidcVerifier(issuer, audience, "https://idp.example/jwks", http_client=_Http())
    claims = await v.verify(good)
    assert claims["sub"] == "bob"
    with pytest.raises(Exception):
        await v.verify(wrong_aud)


# --- M13 / SEC-68: an inert SAML provider must not silently boot --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-68")
def test_saml_provider_config_refuses_to_boot(tmp_path):
    # M13: the manifest advertises a SAML provider that is entirely inert
    # (SamlVerifier.verify raises; resolver selection never reads it). Loading it
    # must FAIL LOUDLY so an operator cannot believe SAML is enforced while the
    # deployment silently runs env-selected auth. oidc / cf-access still load.
    from boltrig.config import load_manifest

    def _write(provider: str) -> str:
        path = tmp_path / f"manifest-{provider}.yaml"
        path.write_text(
            f"tenant_id: acme\norganisation: Acme\nidentity:\n  provider: {provider}\n",
            encoding="utf-8",
        )
        return str(path)

    with pytest.raises(ValueError, match="(?i)saml"):
        load_manifest(_write("saml"))

    # the working providers load cleanly
    assert load_manifest(_write("oidc")).identity.provider == "oidc"
    assert load_manifest(_write("cf-access")).identity.provider == "cf-access"
