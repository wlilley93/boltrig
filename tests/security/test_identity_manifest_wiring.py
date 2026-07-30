"""Manifest OIDC trust is consumed exactly and projected without values."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from boltrig.api import bootstrap
from boltrig.config.settings import Settings
from boltrig.observability.identity_policy import (
    compose_identity_policy,
    identity_policy_projection,
)


def _manifest(
    *,
    issuer: str | None,
    audience: str | None,
    jwks_uri: str | None,
):
    identity = SimpleNamespace(
        issuer=issuer,
        audience=audience,
        jwks_uri=jwks_uri,
    )
    return SimpleNamespace(
        identity=identity,
        role_mappings=(),
        tenant_id="acme",
    )


def test_manifest_oidc_trio_selects_the_generic_verifier(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Verifier:
        def __init__(self, issuer, audience, jwks_uri):
            captured["trust"] = (issuer, audience, jwks_uri)

    expected = object()
    monkeypatch.setattr(bootstrap, "refuse_default_audit_key_in_prod", lambda: None)
    monkeypatch.setattr(bootstrap, "load_settings", lambda: Settings())
    monkeypatch.setattr("boltrig.identity.OidcVerifier", _Verifier)
    monkeypatch.setattr(
        "boltrig.identity.build_principal_resolver",
        lambda **kwargs: captured.update(kwargs) or expected,
    )
    manifest = _manifest(
        issuer="https://id.example",
        audience="boltrig",
        jwks_uri="https://id.example/jwks",
    )

    selected = bootstrap.select_principal_resolver(manifest)

    assert selected is expected
    assert captured["trust"] == (
        "https://id.example",
        "boltrig",
        "https://id.example/jwks",
    )
    assert captured["tenant_id"] == "acme"


def test_manifest_oidc_partial_or_process_drift_refuses_boot(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "refuse_default_audit_key_in_prod", lambda: None)
    monkeypatch.setattr(bootstrap, "load_settings", lambda: Settings())
    with pytest.raises(RuntimeError, match="partial"):
        bootstrap.select_principal_resolver(
            _manifest(
                issuer="https://id.example",
                audience=None,
                jwks_uri=None,
            )
        )

    monkeypatch.setattr(
        bootstrap,
        "load_settings",
        lambda: Settings(
            oidc_issuer="https://other.example",
            oidc_audience="boltrig",
            oidc_jwks_uri="https://other.example/jwks",
        ),
    )
    with pytest.raises(RuntimeError, match="differs"):
        bootstrap.select_principal_resolver(
            _manifest(
                issuer="https://id.example",
                audience="boltrig",
                jwks_uri="https://id.example/jwks",
            )
        )


def test_identity_projection_redacts_every_trust_value() -> None:
    raw = compose_identity_policy(
        _manifest(
            issuer="https://id.private.example",
            audience="private-audience",
            jwks_uri="https://id.private.example/secret-jwks",
        ),
        Settings(),
    )
    projected = identity_policy_projection(raw)
    assert projected["mode"] == "oidc"
    assert projected["oidc"] == {
        "manifest_trio_configured": True,
        "process_trio_configured": False,
        "manifest_trio_state": "complete",
        "process_trio_state": "absent",
        "serving_state": "active_manifest",
        "drift_policy": "exact_match_or_boot_refused",
    }
    assert len(projected["generation"]) == 64
    rendered = repr(projected)
    assert "id.private.example" not in rendered
    assert "private-audience" not in rendered
    assert "secret-jwks" not in rendered
