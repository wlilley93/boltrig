"""Tests for the trusted-Codex dev/prod wall ([2026] VJS-CC-VJS 2, D1).

The wall is the load-bearing safety property: the trusted runtime mints a bearer
without SO_PEERCRED, so it MUST be structurally unreachable under any production
signal or any real ingress posture. These pin that it fails closed.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.codex_trusted_wall import (
    CodexTrustedPostureError,
    require_codex_trusted_posture,
)

_TRUSTED = {"BOLTRIG_DEV_AUTH": "1", "BOLTRIG_CODEX_TRUSTED": "1"}


def test_trusted_dev_posture_passes() -> None:
    require_codex_trusted_posture(dict(_TRUSTED))  # does not raise


def test_missing_dev_auth_is_refused() -> None:
    with pytest.raises(CodexTrustedPostureError, match="BOLTRIG_DEV_AUTH"):
        require_codex_trusted_posture({"BOLTRIG_CODEX_TRUSTED": "1"})


def test_missing_trusted_flag_is_refused() -> None:
    with pytest.raises(CodexTrustedPostureError, match="BOLTRIG_CODEX_TRUSTED"):
        require_codex_trusted_posture({"BOLTRIG_DEV_AUTH": "1"})


@pytest.mark.parametrize(
    "signal",
    [
        {"BOLTRIG_PRODUCTION": "1"},
        {"ENV": "production"},
        {"ENV": "staging"},
        {"BOLTRIG_ENV": "prod"},
        {"APP_ENV": "production"},
    ],
)
def test_any_production_signal_is_refused(signal: dict[str, str]) -> None:
    with pytest.raises(CodexTrustedPostureError, match="production signal"):
        require_codex_trusted_posture({**_TRUSTED, **signal})


@pytest.mark.parametrize(
    "posture",
    [
        {"OIDC_ISSUER": "https://idp", "OIDC_AUDIENCE": "a", "OIDC_JWKS_URI": "https://j"},
        {"CF_ACCESS_TEAM_DOMAIN": "https://t.cloudflareaccess.com", "CF_ACCESS_AUD": "aud"},
        {"BOLTRIG_AUTH_MODE": "session"},
    ],
)
def test_real_ingress_posture_is_refused(posture: dict[str, str]) -> None:
    with pytest.raises(CodexTrustedPostureError, match="ingress posture"):
        require_codex_trusted_posture({**_TRUSTED, **posture})
