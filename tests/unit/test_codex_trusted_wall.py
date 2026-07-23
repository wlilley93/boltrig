"""Tests for the trusted-Codex dev/prod wall ([2026] VJS-CC-VJS 2 D1, 7 J8).

The wall protects ONE thing: a per-cell bearer must never be minted for an
identity the kernel did not attest. Two postures discharge that and these pin
both, plus the two refusals that never relax: the explicit trusted flag and the
production signal. Posture (a) is the legacy single-operator dev box; posture
(b) is the kernel-attested per-cell-uid deployment, under which a real ingress
posture (session login included) may coexist because cell identity is
kernel-attested, not bearer-trusted.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.codex_trusted_wall import (
    CodexTrustedPostureError,
    require_codex_trusted_posture,
)

_TRUSTED = {"BOLTRIG_DEV_AUTH": "1", "BOLTRIG_CODEX_TRUSTED": "1"}
_SESSION = {"BOLTRIG_AUTH_MODE": "session"}


# --- (a) the legacy single-operator dev posture -------------------------------


def test_trusted_dev_posture_passes() -> None:
    require_codex_trusted_posture(dict(_TRUSTED), per_cell_uids=False)  # does not raise


def test_missing_dev_auth_is_refused() -> None:
    with pytest.raises(CodexTrustedPostureError, match="BOLTRIG_DEV_AUTH"):
        require_codex_trusted_posture({"BOLTRIG_CODEX_TRUSTED": "1"}, per_cell_uids=False)


def test_missing_trusted_flag_is_refused() -> None:
    with pytest.raises(CodexTrustedPostureError, match="BOLTRIG_CODEX_TRUSTED"):
        require_codex_trusted_posture({"BOLTRIG_DEV_AUTH": "1"}, per_cell_uids=False)


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
        require_codex_trusted_posture({**_TRUSTED, **signal}, per_cell_uids=False)


@pytest.mark.parametrize(
    "posture",
    [
        {"OIDC_ISSUER": "https://idp", "OIDC_AUDIENCE": "a", "OIDC_JWKS_URI": "https://j"},
        {"CF_ACCESS_TEAM_DOMAIN": "https://t.cloudflareaccess.com", "CF_ACCESS_AUD": "aud"},
        _SESSION,
    ],
)
def test_real_ingress_posture_is_refused(posture: dict[str, str]) -> None:
    with pytest.raises(CodexTrustedPostureError, match="ingress posture"):
        require_codex_trusted_posture({**_TRUSTED, **posture}, per_cell_uids=False)


# --- (b) the kernel-attested per-cell-uid posture -----------------------------


@pytest.mark.invariant("SEC-185")
def test_per_cell_posture_admits_session_auth_without_dev_auth() -> None:
    env = {"BOLTRIG_CODEX_TRUSTED": "1", **_SESSION}
    require_codex_trusted_posture(env, per_cell_uids=True)  # does not raise


@pytest.mark.invariant("SEC-185")
@pytest.mark.parametrize(
    "posture",
    [
        {"OIDC_ISSUER": "https://idp", "OIDC_AUDIENCE": "a", "OIDC_JWKS_URI": "https://j"},
        {"CF_ACCESS_TEAM_DOMAIN": "https://t.cloudflareaccess.com", "CF_ACCESS_AUD": "aud"},
        {},
    ],
)
def test_per_cell_posture_admits_any_ingress(posture: dict[str, str]) -> None:
    # The edge auth mode is not an input to cell identity: with kernel-attested
    # per-cell uids the bearer cannot be minted to a foreign cell whatever the
    # ingress - including none at all.
    env = {"BOLTRIG_CODEX_TRUSTED": "1", **posture}
    require_codex_trusted_posture(env, per_cell_uids=True)  # does not raise


@pytest.mark.invariant("SEC-185")
def test_per_cell_posture_still_requires_the_trusted_flag() -> None:
    with pytest.raises(CodexTrustedPostureError, match="BOLTRIG_CODEX_TRUSTED"):
        require_codex_trusted_posture(dict(_SESSION), per_cell_uids=True)


@pytest.mark.invariant("SEC-185")
def test_per_cell_posture_still_refuses_a_production_signal() -> None:
    env = {"BOLTRIG_CODEX_TRUSTED": "1", "BOLTRIG_PRODUCTION": "1", **_SESSION}
    with pytest.raises(CodexTrustedPostureError, match="production signal"):
        require_codex_trusted_posture(env, per_cell_uids=True)


@pytest.mark.invariant("SEC-185")
def test_session_auth_without_per_cell_uids_is_refused() -> None:
    # The exact regression the wall exists for: a real ingress posture with only
    # an OBSERVED (not kernel-attested) cell identity must stay refused.
    with pytest.raises(CodexTrustedPostureError, match="ingress posture"):
        require_codex_trusted_posture(
            {"BOLTRIG_CODEX_TRUSTED": "1", **_SESSION}, per_cell_uids=False
        )


def test_the_per_cell_probe_is_consulted_when_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boltrig.fleet.codex_trusted_wall as wall

    monkeypatch.setattr(wall, "per_cell_uid_mode_available", lambda env=None: True)
    require_codex_trusted_posture({"BOLTRIG_CODEX_TRUSTED": "1", **_SESSION})
    monkeypatch.setattr(wall, "per_cell_uid_mode_available", lambda env=None: False)
    with pytest.raises(CodexTrustedPostureError, match="ingress posture"):
        require_codex_trusted_posture({"BOLTRIG_CODEX_TRUSTED": "1", **_SESSION})
